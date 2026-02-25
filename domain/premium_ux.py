# -*- coding: utf-8 -*-
import re

def detect_frustration(state: dict) -> bool:
    """
    Senior IT: Empathy Guard.
    Detects if the user is struggling (repeating the same failed step multiple times).
    """
    last_steps = state.get("step_history", [])
    if len(last_steps) < 4:
        return False
        
    # If last 3 steps are 'cancel' or 'undo'
    frustrating_tokens = ["cancel", "undo", "price:ultra", "amount:edit"]
    count = 0
    for step in last_steps[-3:]:
        if any(token in str(step) for token in frustrating_tokens):
            count += 1
            
    return count >= 3

def get_smart_tags(full_ocr_text: str) -> list[str]:
    """
    Senior IT: Smart Tagging.
    Auto-tags invoices based on content keywords.
    """
    t = full_ocr_text.lower()
    tags = []
    rules = {
        "#Remont": ["farba", "pedzel", "narzedzia", "materialy budowlane", "castorama", "leroy", "obi"],
        "#Marketing": ["reklama", "ulotki", "wizytowki", "facebook", "google ads", "druk"],
        "#IT": ["serwer", "domena", "host", "oprogramowanie", "microsoft", "adobe", "komputer"],
        "#Pojazdy": ["paliwo", "opony", "olej", "mechanik", "części zamienne"]
    }
    
    for tag, keywords in rules.items():
        if any(k in t for k in keywords):
            tags.append(tag)
            
    return tags
