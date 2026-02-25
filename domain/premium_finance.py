# -*- coding: utf-8 -*-
import requests
from datetime import datetime, timedelta
import logging

def get_nbp_rate(currency: str, date_str: str) -> float:
    """
    Fetches the NBP exchange rate for the day preceding the invoice date.
    """
    if currency.upper() == "PLN":
        return 1.0
    
    try:
        # NBP requires the rate from the day BEFORE the invoice date
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        for i in range(1, 10): # Try up to 10 days back (to skip holidays/weekends)
            prev_date = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
            url = f"https://api.nbp.pl/api/exchangerates/rates/a/{currency}/{prev_date}/?format=json"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return float(resp.json()["rates"][0]["mid"])
    except Exception as e:
        logging.error(f"NBP Rate Error: {e}")
    
    return 1.0

def check_nip_white_list(nip: str) -> dict:
    """
    Checks if the company is on the MF White List.
    """
    clean_nip = "".join(filter(str.isdigit, nip))
    if len(clean_nip) != 10:
        return {"ok": False, "msg": "Niepoprawny NIP"}
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"https://wl-api.mf.gov.pl/api/search/nip/{clean_nip}?date={today}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("result", {}).get("subject", {}).get("statusVat", "")
            if status == "Czynny":
                return {"ok": True, "msg": "Aktywny płatnik VAT"}
            return {"ok": False, "msg": f"Status VAT: {status or 'Nieznany'}"}
    except:
        pass
    return {"ok": True, "msg": "Nie udało się sprawdzić białej listy (serwer MF nie odpowiada)"}
