# -*- coding: utf-8 -*-
"""Activation d'un compte sans Active Directory.

Parcours (réservé aux agents qui n'ont pas d'identifiant AD) :
1. le valideur de l'agent (ou un administrateur) génère un **code d'activation** à usage unique (valable 7 jours), remis à l'agent avec un **QR code** ;
2. l'agent saisit son **matricule** et ce code (le QR code les préremplit) ;
3. il saisit son **smartphone** : un **code SMS** à 6 chiffres lui est envoyé (API Ville / APM) ; le numéro n'est enregistré qu'une fois le code SMS saisi ;
3 bis. il peut indiquer son **adresse e-mail** (facultatif : sans adresse, ses confirmations de demandes et de validations lui arrivent par SMS) ;
4. il choisit son **mot de passe** local ; son compte est alors utilisable (connexion par identifiant ou matricule).

Durcissement : réponse identique que le matricule existe ou non ; 5 essais de code d'activation puis verrouillage (nouveau code nécessaire) ; code SMS à usage unique valable
10 minutes, 5 essais, 3 envois au plus et 60 s entre deux ; limites par adresse IP et par matricule ; seuls des hachés sont stockés ; chaque étape est journalisée ;
l'agent est prévenu par e-mail quand son compte est activé (s'il a une adresse) ;
**mot de passe oublié** : possible pour les comptes dont le smartphone a été contrôlé (SMS à 6 chiffres, 10 minutes, 5 essais, 3 envois par heure, même réponse que le compte existe ou non ; les connexions mémorisées sont coupées ; prévenance par e-mail ou SMS).
"""
import datetime as dt
import hashlib
import hmac
import io
import re
import secrets
import time

from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash

import apm
import audit_logs
import config
import ratelimit
import remember
from db import get_db, user_label
from http_utils import error

bp = Blueprint("activation", __name__, url_prefix="/api/activation")

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"          # sans 0/O/1/I : lisible sur papier
VALID_DAYS = 7
OTP_MINUTES = 10
OTP_MAX_SENDS = 3
OTP_RESEND_SECONDS = 60
MAX_CODE_TRIES = 5
MAX_OTP_TRIES = 5
SESSION_SECONDS = 1800
GENERIC = "Informations incorrectes ou code expiré"


def new_code():
    """Code d'activation « XXXXX-XXXXX » (50 bits)."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
    return raw[:5] + "-" + raw[5:]


def norm_code(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _hash(activation_id, kind, value):
    return hashlib.sha256(("%s:%s:%s" % (activation_id, kind, value)).encode("utf-8")).hexdigest()


def _same(a, b):
    return hmac.compare_digest(a or "", b or "")


def normalize_mobile(value):
    """Smartphone français « 06XXXXXXXX » / « 07XXXXXXXX » (acceptés : espaces, +33, 0033) ; None si invalide."""
    digits = re.sub(r"[\s.\-()]", "", value or "")
    digits = re.sub(r"^(\+33|0033)", "0", digits)
    return digits if re.fullmatch(r"0[67]\d{8}", digits) else None


def mask_mobile(mobile):
    return "%s ** ** ** %s" % (mobile[:2], mobile[-2:])


def qr_svg(text):
    """QR code (SVG) du texte, ou None si la bibliothèque `segno` n'est pas installée."""
    try:
        import segno
    except ImportError:
        return None
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", xmldecl=False, svgns=True, scale=5, border=2)
    return out.getvalue().decode("utf-8")


def password_error(password, user):
    password = password or ""
    if len(password) < 10:
        return "Le mot de passe doit contenir au moins 10 caractères"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Le mot de passe doit contenir des lettres et des chiffres"
    lowered = password.lower()
    for forbidden in (user["login"], user["matricule"], user["mobile"]):
        if forbidden and str(forbidden).lower() in lowered:
            return "Le mot de passe ne doit pas contenir votre identifiant, votre matricule ou votre numéro"
    return None


def _now():
    return dt.datetime.now()


def _log(event, user, success, reason=""):
    audit_logs.log_login(event, (user["login"] if user else ""), (user["id"] if user else None), success, reason, "activation")


def _sms(mobile, text, subject, log_text=None):
    """Envoie un SMS par l'APM et le journalise dans le journal des e-mails (canal « sms », numéro masqué, état envoyé ou échec).
    Le code à usage unique n'est JAMAIS enregistré : le journal ne garde que l'objet (ou `log_text`, jamais le message qui contient le code)."""
    masked = mask_mobile(mobile)
    try:
        apm.send_sms(mobile, text)
    except apm.ApmError as exc:
        audit_logs.log_mail(masked, subject, "sms", "echec", str(exc), log_text or subject)
        raise
    audit_logs.log_mail(masked, subject, "sms", "envoye", "", log_text or subject)


def _open_activation(db, user_id):
    """Activation en cours (ni utilisée, ni annulée, ni expirée) d'un compte."""
    return db.execute(
        "SELECT * FROM activations WHERE user_id=? AND utilise_le IS NULL AND annule_le IS NULL AND expire_le > ? ORDER BY id DESC LIMIT 1",
        (user_id, _now())).fetchone()


def _session_activation(db):
    """Activation liée à la session (étape 1 réussie), si elle est encore valable."""
    info = session.get("act") or {}
    if not info or info.get("exp", 0) < time.time():
        return None
    row = db.execute("SELECT * FROM activations WHERE id=? AND utilise_le IS NULL AND annule_le IS NULL AND expire_le > ?", (info.get("id"), _now())).fetchone()
    return row


def init_activation(app, login_required, can_manage, scope_ids, audit_user):
    # ------------------------------------------------------------------ génération du code (valideur / administrateur)
    @app.route("/api/users/<int:uid>/activation", methods=["POST"])
    @login_required
    def activation_create(uid):
        if not can_manage(request.user):
            return error("Accès réservé aux administrateurs et valideurs", 403)
        db = get_db()
        try:
            user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not user or not user["actif"] or user["role"] == "administrateur":
                return error("Personne introuvable ou inactive", 404)
            if not request.user.get("admin") and (uid == request.user["id"] or uid not in set(scope_ids(db, request.user))):
                return error("Cette personne n'est pas dans votre périmètre", 403)
            if (user["ad_login"] or "").strip():
                return error("Cette personne a un compte Active Directory : elle se connecte avec son mot de passe de la Ville", 400)
            if not (user["matricule"] or "").strip():
                return error("Le matricule de la personne est obligatoire (il sert à l'activation)", 400)
            db.execute("UPDATE activations SET annule_le=? WHERE user_id=? AND utilise_le IS NULL AND annule_le IS NULL", (_now(), uid))
            code = new_code()
            expire = _now() + dt.timedelta(days=VALID_DAYS)
            aid = db.execute("INSERT INTO activations (user_id, code_hash, cree_par, expire_le) VALUES (?,?,?,?)", (uid, "", request.user["id"], expire)).lastrowid
            db.execute("UPDATE activations SET code_hash=? WHERE id=?", (_hash(aid, "code", norm_code(code)), aid))
            audit_user(db, uid, user["login"], request.user, "creation", "code_activation", "", "généré (valable %d jours)" % VALID_DAYS, "Code d'activation du compte sans AD")
            db.commit()
            base = (config.MOBILE_URL or "").rstrip("/")
            url = "%s/#activation=%s.%s" % (base, user["matricule"].strip(), code) if base else None
            return jsonify({"code": code, "matricule": user["matricule"].strip(), "nom": user_label(user), "expire_le": expire.strftime("%d/%m/%Y"),
                            "url": url, "qr_svg": qr_svg(url) if url else None, "mobile_url_configuree": bool(base)})
        finally:
            db.close()

    # ------------------------------------------------------------------ étape 1 : matricule + code
    @bp.route("/start", methods=["POST"])
    def start():
        data = request.get_json(force=True, silent=True) or {}
        matricule = (data.get("matricule") or "").strip()
        code = norm_code(data.get("code"))
        ip_bucket, mat_bucket = "act:" + (request.remote_addr or "?"), "actm:" + matricule.lower()[:30]
        if ratelimit.blocked(ip_bucket, 10, 900) or ratelimit.blocked(mat_bucket, 6, 900):
            return error("Trop de tentatives, réessayez dans quelques minutes", 429)
        db = get_db()
        try:
            user = db.execute("SELECT * FROM users WHERE matricule=? AND actif=1 AND ad_login='' AND role<>'administrateur'", (matricule,)).fetchone() if matricule else None
            act = _open_activation(db, user["id"]) if user else None
            ok = bool(act) and _same(act["code_hash"], _hash(act["id"], "code", code)) and act["essais"] < MAX_CODE_TRIES
            if not ok:
                ratelimit.record(ip_bucket)
                ratelimit.record(mat_bucket)
                if act:
                    tries = act["essais"] + 1
                    db.execute("UPDATE activations SET essais=? WHERE id=?", (tries, act["id"]))
                    if tries >= MAX_CODE_TRIES:
                        db.execute("UPDATE activations SET annule_le=? WHERE id=?", (_now(), act["id"]))        # verrouillée : nouveau code nécessaire
                    db.commit()
                    _log("activation", user, False, "code_incorrect" + ("_verrouille" if tries >= MAX_CODE_TRIES else ""))
                else:
                    _log("activation", user, False, "inconnu_ou_expire")
                return error(GENERIC, 400)                      # même réponse dans tous les cas : on ne révèle pas si le matricule existe
            db.execute("UPDATE activations SET etape='sms' WHERE id=?", (act["id"],))
            db.commit()
            session.clear()
            session["act"] = {"id": act["id"], "exp": time.time() + SESSION_SECONDS}
            _log("activation", user, True, "code_valide")
            return jsonify({"etape": "sms"})
        finally:
            db.close()

    # ------------------------------------------------------------------ étape 2 : smartphone -> SMS
    @bp.route("/sms", methods=["POST"])
    def sms():
        db = get_db()
        try:
            act = _session_activation(db)
            if not act or act["etape"] not in ("sms", "otp"):
                return error(GENERIC, 400)
            mobile = normalize_mobile((request.get_json(force=True, silent=True) or {}).get("mobile"))
            if not mobile:
                return error("Numéro de smartphone invalide (06 ou 07, 10 chiffres)", 400)
            if act["otp_envois"] >= OTP_MAX_SENDS:
                return error("Nombre d'envois de SMS atteint : demandez un nouveau code d'activation à votre responsable (valideur)", 429)
            last = act["otp_dernier_envoi"]
            if last and (_now() - last).total_seconds() < OTP_RESEND_SECONDS:
                return error("Patientez une minute avant de demander un nouveau SMS", 429)
            other = db.execute("SELECT 1 FROM users WHERE mobile=? AND id<>? AND mobile_verifie_le IS NOT NULL", (mobile, act["user_id"])).fetchone()
            if other:
                return error("Ce numéro ne peut pas être utilisé : contactez votre responsable (valideur)", 400)
            otp = "%06d" % secrets.randbelow(1000000)
            db.execute("UPDATE activations SET etape='otp', mobile_attente=?, otp_hash=?, otp_expire=?, otp_envois=otp_envois+1, otp_dernier_envoi=?, otp_essais=0 WHERE id=?",
                       (mobile, _hash(act["id"], "otp", otp), _now() + dt.timedelta(minutes=OTP_MINUTES), _now(), act["id"]))
            db.commit()
            try:
                _sms(mobile, "Suivi des congés : votre code de vérification est %s (valable %d minutes). Ne le communiquez à personne." % (otp, OTP_MINUTES),
                     "SMS d'activation : code de contrôle du smartphone")
            except apm.ApmError as exc:
                app.logger.error("Activation : SMS non envoyé : %s", exc)
                return error("Le SMS n'a pas pu être envoyé, réessayez dans un instant", 502)
            user = db.execute("SELECT id, login FROM users WHERE id=?", (act["user_id"],)).fetchone()
            _log("activation", user, True, "sms_envoye")
            return jsonify({"etape": "otp", "mobile": mask_mobile(mobile), "valable_minutes": OTP_MINUTES})
        finally:
            db.close()

    # ------------------------------------------------------------------ étape 3 : code SMS
    @bp.route("/otp", methods=["POST"])
    def otp():
        db = get_db()
        try:
            act = _session_activation(db)
            if not act or act["etape"] != "otp" or not act["otp_hash"]:
                return error(GENERIC, 400)
            user = db.execute("SELECT * FROM users WHERE id=?", (act["user_id"],)).fetchone()
            value = re.sub(r"\D", "", (request.get_json(force=True, silent=True) or {}).get("code") or "")
            if not act["otp_expire"] or act["otp_expire"] < _now():
                return error("Code SMS expiré : demandez-en un nouveau", 400)
            tries = act["otp_essais"] + 1
            if not _same(act["otp_hash"], _hash(act["id"], "otp", value)):
                locked = tries >= MAX_OTP_TRIES
                db.execute("UPDATE activations SET otp_essais=? WHERE id=?", (tries, act["id"]))
                if locked:
                    db.execute("UPDATE activations SET annule_le=? WHERE id=?", (_now(), act["id"]))
                db.commit()
                _log("activation", user, False, "sms_incorrect" + ("_verrouille" if locked else ""))
                return error("Code SMS incorrect" + (" : l'activation est verrouillée, demandez un nouveau code à votre responsable (valideur)" if locked else ""), 400)
            db.execute("UPDATE users SET mobile=?, mobile_verifie_le=? WHERE id=?", (act["mobile_attente"], _now(), act["user_id"]))
            db.execute("UPDATE activations SET etape='email', otp_hash='' WHERE id=?", (act["id"],))
            db.commit()
            _log("activation", user, True, "smartphone_verifie")
            return jsonify({"etape": "email", "a_deja_un_email": bool((user["email"] or "").strip())})
        finally:
            db.close()

    # ------------------------------------------------------------------ étape 3 bis : adresse e-mail (facultative)
    @bp.route("/email", methods=["POST"])
    def email():
        """Adresse e-mail facultative. Sans adresse, les confirmations de demandes et de validations arrivent par SMS."""
        db = get_db()
        try:
            act = _session_activation(db)
            if not act or act["etape"] != "email":
                return error(GENERIC, 400)
            user = db.execute("SELECT * FROM users WHERE id=?", (act["user_id"],)).fetchone()
            address = ((request.get_json(force=True, silent=True) or {}).get("email") or "").strip().lower()
            if address:
                if len(address) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", address):
                    return error("Adresse e-mail invalide", 400)
                if db.execute("SELECT 1 FROM users WHERE lower(email)=? AND id<>?", (address, user["id"])).fetchone():
                    return error("Cette adresse ne peut pas être utilisée : contactez votre responsable (valideur)", 400)
                db.execute("UPDATE users SET email=? WHERE id=?", (address, user["id"]))
                db.execute("UPDATE agents SET email=? WHERE agent_user_id=?", (address, user["id"]))
            db.execute("UPDATE activations SET etape='motdepasse' WHERE id=?", (act["id"],))
            db.commit()
            _log("activation", user, True, "email_renseigne" if address else "sans_email")
            return jsonify({"etape": "motdepasse", "sms_a_la_place": not address and not (user["email"] or "").strip()})
        finally:
            db.close()

    # ------------------------------------------------------------------ étape 4 : mot de passe
    @bp.route("/password", methods=["POST"])
    def password():
        db = get_db()
        try:
            act = _session_activation(db)
            if not act or act["etape"] != "motdepasse":
                return error(GENERIC, 400)
            user = db.execute("SELECT * FROM users WHERE id=?", (act["user_id"],)).fetchone()
            data = request.get_json(force=True, silent=True) or {}
            if data.get("password") != data.get("confirm"):
                return error("Les deux mots de passe ne correspondent pas", 400)
            problem = password_error(data.get("password"), user)
            if problem:
                return error(problem, 400)
            db.execute("UPDATE users SET mot_de_passe=? WHERE id=?", (generate_password_hash(data["password"]), user["id"]))
            remember.revoke_all(db, user["id"])
            db.execute("UPDATE activations SET utilise_le=?, etape='termine' WHERE id=?", (_now(), act["id"]))
            audit_user(db, user["id"], user["login"], {"id": user["id"], "login": user["login"]}, "modification", "mot_de_passe", "***", "défini", "Activation du compte (code + SMS)")
            db.commit()
            session.clear()
            _log("activation", user, True, "compte_active")
            if (user["email"] or "").strip():
                try:
                    import mailer
                    mailer.send_mail(user["email"], "[Suivi congés] Votre compte est activé",
                                     "Bonjour,\n\nVotre compte du suivi des congés vient d'être activé avec votre numéro de smartphone %s.\n"
                                     "Si vous n'êtes pas à l'origine de cette activation, prévenez immédiatement votre responsable (valideur)." % mask_mobile(user["mobile"] or act["mobile_attente"]),
                                     template="activation")
                except Exception as exc:  # noqa: BLE001 - la notification ne bloque pas l'activation
                    app.logger.warning("Activation : e-mail de notification non envoyé : %s", exc)
            return jsonify({"ok": True, "login": user["login"], "matricule": user["matricule"]})
        finally:
            db.close()

    # ------------------------------------------------------------------ mot de passe oublié (smartphone contrôlé)
    def _reset_user(db, ident):
        """Compte qui peut réinitialiser son mot de passe par SMS : actif, non administrateur, smartphone contrôlé, identifié par son matricule ou son identifiant."""
        rows = db.execute(
            "SELECT * FROM users WHERE actif=1 AND admin=0 AND role<>'administrateur' AND mobile_verifie_le IS NOT NULL AND mobile<>'' "
            "AND (matricule=? OR lower(login)=lower(?))", (ident, ident)).fetchall() if ident else []
        return rows[0] if len(rows) == 1 else None

    @bp.route("/forgot", methods=["POST"])
    def forgot():
        """Envoie un code par SMS au smartphone contrôlé du compte. Réponse identique que le compte existe ou non."""
        ident = ((request.get_json(force=True, silent=True) or {}).get("identifiant") or "").strip()
        ip_bucket, id_bucket = "forgot:" + (request.remote_addr or "?"), "forgotm:" + ident.lower()[:40]
        if ratelimit.blocked(ip_bucket, 6, 900) or ratelimit.blocked(id_bucket, 4, 900):
            return error("Trop de demandes, réessayez dans quelques minutes", 429)
        ratelimit.record(ip_bucket)
        ratelimit.record(id_bucket)
        db = get_db()
        try:
            user = _reset_user(db, ident)
            if user:
                recent = db.execute("SELECT COUNT(*) AS n FROM activations WHERE user_id=? AND etape='reset' AND cree_le > ?",
                                    (user["id"], _now() - dt.timedelta(hours=1))).fetchone()["n"]
                if recent < OTP_MAX_SENDS:
                    otp = "%06d" % secrets.randbelow(1000000)
                    db.execute("UPDATE activations SET annule_le=? WHERE user_id=? AND etape='reset' AND utilise_le IS NULL AND annule_le IS NULL", (_now(), user["id"]))
                    aid = db.execute("INSERT INTO activations (user_id, code_hash, etape, expire_le, mobile_attente, otp_expire, otp_envois, otp_dernier_envoi) VALUES (?,?,?,?,?,?,1,?)",
                                     (user["id"], "", "reset", _now() + dt.timedelta(minutes=OTP_MINUTES), user["mobile"], _now() + dt.timedelta(minutes=OTP_MINUTES), _now())).lastrowid
                    db.execute("UPDATE activations SET otp_hash=? WHERE id=?", (_hash(aid, "otp", otp), aid))
                    db.commit()
                    try:
                        _sms(user["mobile"], "Suivi congés : code de réinitialisation de votre mot de passe : %s (valable %d minutes). "
                                             "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message." % (otp, OTP_MINUTES),
                             "SMS de réinitialisation : code de vérification")
                        _log("activation", user, True, "reinit_sms_envoye")
                    except apm.ApmError as exc:
                        app.logger.error("Mot de passe oublié : SMS non envoyé : %s", exc)
                else:
                    _log("activation", user, False, "reinit_limite")
            else:
                _log("activation", None, False, "reinit_inconnu")
            return jsonify({"ok": True})          # même réponse dans tous les cas : on ne révèle pas si le compte existe
        finally:
            db.close()

    @bp.route("/reset", methods=["POST"])
    def reset():
        """Nouveau mot de passe, avec le code reçu par SMS."""
        data = request.get_json(force=True, silent=True) or {}
        ident = (data.get("identifiant") or "").strip()
        code = re.sub(r"\D", "", data.get("code") or "")
        ip_bucket, id_bucket = "reset:" + (request.remote_addr or "?"), "resetm:" + ident.lower()[:40]
        if ratelimit.blocked(ip_bucket, 10, 900) or ratelimit.blocked(id_bucket, 6, 900):
            return error("Trop de tentatives, réessayez dans quelques minutes", 429)
        db = get_db()
        try:
            user = _reset_user(db, ident)
            act = db.execute("SELECT * FROM activations WHERE user_id=? AND etape='reset' AND utilise_le IS NULL AND annule_le IS NULL AND otp_expire > ? ORDER BY id DESC LIMIT 1",
                             (user["id"], _now())).fetchone() if user else None
            if not act or act["otp_essais"] >= MAX_OTP_TRIES or not _same(act["otp_hash"], _hash(act["id"], "otp", code)):
                ratelimit.record(ip_bucket)
                ratelimit.record(id_bucket)
                if act:
                    tries = act["otp_essais"] + 1
                    db.execute("UPDATE activations SET otp_essais=? WHERE id=?", (tries, act["id"]))
                    if tries >= MAX_OTP_TRIES:
                        db.execute("UPDATE activations SET annule_le=? WHERE id=?", (_now(), act["id"]))
                    db.commit()
                _log("activation", user, False, "reinit_code_incorrect")
                return error("Code incorrect ou expiré", 400)
            if data.get("password") != data.get("confirm"):
                return error("Les deux mots de passe ne correspondent pas", 400)
            problem = password_error(data.get("password"), user)
            if problem:
                return error(problem, 400)
            db.execute("UPDATE users SET mot_de_passe=? WHERE id=?", (generate_password_hash(data["password"]), user["id"]))
            remember.revoke_all(db, user["id"])                                  # les connexions mémorisées sont coupées
            db.execute("UPDATE activations SET utilise_le=?, etape='reset_termine' WHERE id=?", (_now(), act["id"]))
            audit_user(db, user["id"], user["login"], {"id": user["id"], "login": user["login"]}, "modification", "mot_de_passe", "***", "réinitialisé", "Mot de passe oublié (code SMS)")
            db.commit()
            _log("activation", user, True, "reinit_effectuee")
            notice = "Suivi congés : votre mot de passe vient d'être réinitialisé. Si vous n'en êtes pas à l'origine, prévenez votre responsable (valideur)."
            if (user["email"] or "").strip():
                try:
                    import mailer
                    mailer.send_mail(user["email"], "[Suivi congés] Votre mot de passe a été réinitialisé", notice.replace("Suivi congés : ", ""), template="reinitialisation")
                except Exception as exc:  # noqa: BLE001
                    app.logger.warning("Réinitialisation : e-mail non envoyé : %s", exc)
            else:
                try:
                    _sms(user["mobile"], notice, "SMS de prévenance : mot de passe réinitialisé", notice)
                except apm.ApmError as exc:
                    app.logger.warning("Réinitialisation : SMS de prévenance non envoyé : %s", exc)
            return jsonify({"ok": True, "matricule": user["matricule"] or user["login"]})
        finally:
            db.close()

    app.register_blueprint(bp)
