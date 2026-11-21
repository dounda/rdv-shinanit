# -*- coding: utf-8 -*-
"""
Vérification des rendez-vous שיננית Meuhedet - version GitHub Actions (une tournée par lancement).
Lit la page publique "איתור שירותים" (sans connexion) : 1er créneau libre de chaque שיננית (3 mois).
Envoie la liste sur Telegram quand elle change, et une alerte quand un créneau plus proche apparaît.
"""
import json
import os
import random
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

SHINANIOT = {
    # Ramot - Kanyon Ramot, שד' גולדה מאיר 255
    "760000000000010633": "אלישע רפאלה · Ramot",
    "760000000000011330": "מושיחוב נטלה · Ramot",
    "760000000000010515": "צ'ונה אלאדי אפרת · Ramot",
    "760000000000011333": "חרוב באדר (שינן) · Ramot",
    # Maale Adumim - כיכר יהלום 5
    "950000000000011303": "אדר גל · Maale Adumim",
    "950000000000010904": "שליו אורטל · Maale Adumim",
    "950000000000010511": "בובלי אוה · Maale Adumim",
    # Mevaseret Tsion - חרמון 2
    "970000000000011190": "טויפלייבה אולה · Mevaseret", "000881070937000613000000000000": "Dr טויטו סברין (gyné) · Ramot",
}
RECHERCHES = [(110, "שיננית רמות"), (110, "שיננית מעלה אדומים"), (110, "שיננית מבשרת"), (100, "טויטו")]
URL_RECHERCHE = "https://www.meuhedet.co.il/search?rn=1065&mod={}&q="
ETAT = Path(__file__).resolve().parent / "etat.json"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def fmt(d):
    return f"{JOURS[d.weekday()]} {d:%d/%m/%Y}"


def telegram(msg):
    print("TELEGRAM >", msg.replace("\n", " | "))
    if not (TOKEN and CHAT_ID):
        return
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": msg}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20)


def lire_page(page, requete):
    resultats = {}
    with page.expect_response(lambda r: "ExternalIndexerAddedData" in r.url, timeout=60000) as rep:
        page.goto(URL_RECHERCHE.format(requete[0]) + urllib.parse.quote(requete[1]), timeout=60000)
    for e in rep.value.json().get("Entries", []):
        pid = e.get("Id", "").split("_")[-1]
        q = (e.get("FirstQueues") or {}).get("Clinic")
        if q and q.get("AppointmentDate"):
            resultats[pid] = (date.fromisoformat(q["AppointmentDate"][:10]), (q.get("FromTime") or "")[11:16])
        else:
            resultats[pid] = (None, "")
    return resultats


def main():
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    meilleures = {k: (date.fromisoformat(v) if v else None)
                  for k, v in etat.get("meilleures", {}).items() if k in SHINANIOT}

    trouves = {}
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = nav.new_page(locale="he-IL", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
        for requete in RECHERCHES:
            try:
                trouves.update(lire_page(page, requete))
            except Exception as e:
                print(f"Recherche « {requete} » : échec ({e.__class__.__name__}: {e})")
            page.wait_for_timeout(random.uniform(2000, 4000))
        nav.close()

    resultats = {pid: trouves[pid] for pid in SHINANIOT if pid in trouves}
    if not resultats:
        echecs = etat.get("echecs", 0) + 1
        etat["echecs"] = echecs
        print("Aucune réponse de Meuhedet")
        if echecs == 3:
            telegram("⚠️ Le site Meuhedet ne répond plus aux vérifications depuis GitHub (3 fois de suite).")
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    etat["echecs"] = 0

    ordre = sorted(resultats.items(), key=lambda x: x[1][0] or date.max)
    for pid, (d, h) in ordre:
        print(f"{SHINANIOT[pid]:36} → " + (f"{fmt(d)} à {h}" if d else "rien dans les 3 prochains mois"))

    nouvelles = []
    for pid, (d, h) in resultats.items():
        connue, ancienne = pid in meilleures, meilleures.get(pid)
        if d and connue and (ancienne is None or d < ancienne):
            nouvelles.append(f"{SHINANIOT[pid]} : {fmt(d)} à {h}"
                             + (f" (avant : {fmt(ancienne)})" if ancienne else " (avant : rien dans les 3 mois)"))
        meilleures[pid] = d
    if nouvelles:
        telegram("🦷 RENDEZ-VOUS LIBÉRÉ !\n" + "\n".join(nouvelles) + "\nRéserve vite sur l'appli Meuhedet !")

    resume = "\n".join(f"• {SHINANIOT[pid]} : " + (f"{fmt(d)} à {h}" if d else "rien dans les 3 mois")
                       for pid, (d, h) in ordre)
    if resume != etat.get("dernier_resume"):
        telegram("📋 Rendez-vous les plus proches :\n" + resume)
        etat["dernier_resume"] = resume
    etat["meilleures"] = {k: (v.isoformat() if v else None) for k, v in meilleures.items()}
    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
