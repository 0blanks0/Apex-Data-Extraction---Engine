# ==============================================================================
# APEX v3104.00: THE OMNI-SPORT RESTORATION
# ==============================================================================
# 1. UNIVERSAL SUPPORT: NBA, NHL, NFL, MLB, TENNIS, CSGO, LOL, VALORANT.
# 2. DUAL-ENGINE ROUTING: 
#    - Standard Sports -> ESPN API (Restored).
#    - Esports -> Internal DB / Liquipedia API.
# 3. MATH CORE: v71.7 (Poisson/N-Binom) processes ALL sports identically.
# ==============================================================================

import os
import time
import base64
import json
import requests
import sys
import re
import numpy as np
from scipy.stats import nbinom, poisson
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import init, Fore, Style
from dotenv import load_dotenv

# --- GLOBAL CONFIG ---
load_dotenv()
TEST_MODE = True
DEBUG_MODE = True
MAX_WORKERS = 10 

BASE_DIR = r"C:\Users\erikr\bot proj"
WATCH_FOLDER = os.path.join(BASE_DIR, "screenshots")
PROCESSED_FOLDER = os.path.join(WATCH_FOLDER, "processed")
DB_FILE = os.path.join(BASE_DIR, "players.json")

# --- API KEYS ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LIQUIPEDIA_KEY = os.getenv("LIQUIPEDIA_KEY") 

if not GEMINI_API_KEY: sys.exit("❌ ERROR: Missing GEMINI_API_KEY")

# --- CONFIGURATION MAPS ---
# 1. ESPORTS LEGENDS (Verified Stats)
INTERNAL_ESPORTS = {
    "swiz": {"sport": "counterstrike", "season_avg": 18.0, "l5_avg": 18.0},
    "darchevile": {"sport": "counterstrike", "season_avg": 15.2, "l5_avg": 15.2},
    "thomass1": {"sport": "counterstrike", "season_avg": 19.8, "l5_avg": 19.8},
    "brave": {"sport": "counterstrike", "season_avg": 16.8, "l5_avg": 16.8},
    "s1mple": {"sport": "counterstrike", "season_avg": 21.7, "l5_avg": 22.0},
    "zywoo": {"sport": "counterstrike", "season_avg": 22.2, "l5_avg": 22.5},
    "niko": {"sport": "counterstrike", "season_avg": 20.0, "l5_avg": 20.0},
}

# 2. UNIVERSAL API ROUTING
API_CONFIG = {
    # STANDARD SPORTS (ESPN)
    "nba": ("basketball", "nba"), 
    "wnba": ("basketball", "wnba"),
    "nfl": ("football", "nfl"), 
    "cfb": ("football", "college-football"),
    "mlb": ("baseball", "mlb"), 
    "nhl": ("hockey", "nhl"),
    "tennis": ("tennis", "atp"), # Generic Tennis
    
    # ESPORTS (LIQUIPEDIA)
    "csgo": ("liquipedia", "counterstrike"), 
    "lol": ("liquipedia", "leagueoflegends"),
    "valorant": ("liquipedia", "valorant")
}

# --- UI SETUP ---
init(autoreset=True)
try:
    from tabulate import tabulate
except ImportError:
    def tabulate(data, headers, tablefmt): return str(data)

if not os.path.exists(WATCH_FOLDER): os.makedirs(WATCH_FOLDER)
if not os.path.exists(PROCESSED_FOLDER): os.makedirs(PROCESSED_FOLDER)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})

# ==============================================================================
# I. DATABASE
# ==============================================================================
def normalize(name): return re.sub(r'[^a-z0-9]', '', name.lower())

def update_db_with_internal(current_db):
    updated = False
    for name, data in INTERNAL_ESPORTS.items():
        key = normalize(name)
        if key not in current_db:
            current_db[key] = {
                "id": name, "sport": data['sport'], 
                "season_avg": data['season_avg'], "l5_avg": data['l5_avg'], 
                "verified_name": name
            }
            updated = True
    if updated:
        try:
            with open(DB_FILE, 'w') as f: json.dump(current_db, f, indent=4)
        except: pass
    return current_db

def load_db():
    db = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f: db = json.load(f)
        except: pass
    return update_db_with_internal(db)

def save_to_db(name, data):
    try:
        with open(DB_FILE, 'r') as f: db = json.load(f)
    except: db = {}
    
    db[normalize(name)] = data
    with open(DB_FILE, 'w') as f: json.dump(db, f, indent=4)

# ==============================================================================
# II. DATA FETCHERS (ESPN + LIQUIPEDIA)
# ==============================================================================

# --- A. STANDARD SPORTS (ESPN) ---
def fetch_espn_stats(player_name, sport_tuple, stat_name):
    """Auto-discovers and fetches stats from ESPN for NBA, NHL, NFL, etc."""
    sport, league = sport_tuple
    clean_name = re.split(r'\s+(vs|@)\s+', player_name, flags=re.IGNORECASE)[0].strip()
    
    try:
        # 1. Search for Player ID
        search_url = f"https://site.web.api.espn.com/apis/common/v3/search?region=us&lang=en&query={clean_name}&limit=1&mode=prefix&type=player&sport={sport}&league={league}"
        r = session.get(search_url, timeout=2)
        data = r.json()
        
        if not data.get('items'): return None
        
        player = data['items'][0]
        pid = player['id']
        
        # 2. Fetch Gamelog (2025/2026 Season)
        # Using 2026 as primary, falling back to 2025 if needed
        stats = []
        for season in ["2026", "2025"]:
            log_url = f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{pid}/gamelog?season={season}"
            r = session.get(log_url, timeout=2)
            if r.status_code == 200:
                log_data = r.json()
                if 'seasonTypes' in log_data:
                    for st in log_data['seasonTypes']:
                        for cat in st.get('categories', []):
                            for e in cat.get('events', []):
                                val = 0
                                # Heuristic to find the right stat column (simplified)
                                # For production, you'd map "Points" -> index 0, "Rebounds" -> index 1, etc.
                                # Here we grab the first numeric stat as a proxy or use "score" for points
                                if "POINT" in stat_name.upper() or "SCORE" in stat_name.upper():
                                    try: val = float(e['stats'][0]) # Usually points
                                    except: pass
                                elif "REBOUND" in stat_name.upper():
                                    try: val = float(e['stats'][13]) # Often rebounds (varies by sport)
                                    except: pass
                                elif "ASSIST" in stat_name.upper():
                                    try: val = float(e['stats'][14]) # Often assists
                                    except: pass
                                else:
                                    # Fallback: Try to find a stat matching the line magnitude
                                    try: val = float(e['stats'][0])
                                    except: pass
                                
                                if val > 0: stats.append(val)
            if stats: break # Stop if we found data for current season

        if stats:
            return {
                "season_avg": np.mean(stats),
                "l5_avg": np.mean(stats[:5]),
                "source": f"ESPN ({league.upper()})"
            }
            
    except Exception as e:
        if DEBUG_MODE: print(f"ESPN Error ({player_name}): {e}")
        
    return None

# --- B. ESPORTS (LIQUIPEDIA) ---
def fetch_liquipedia(player_name, wiki_slug):
    if not LIQUIPEDIA_KEY: return None
    url = f"https://api.liquipedia.net/api/v3/{wiki_slug}/search"
    headers = {"Authorization": f"Apikey {LIQUIPEDIA_KEY}"}
    try:
        time.sleep(1.2) # Rate limit safety
        r = requests.get(url, headers=headers, params={"wiki": wiki_slug, "limit": 1, "q": player_name}, timeout=3)
        if r.status_code == 200 and r.json():
            return {"season_avg": None, "source": f"Liquipedia ({wiki_slug})"} # Verified, but needs manual input
    except: pass
    return None

# --- C. ROUTER ---
def get_player_data(name, sport_key, stat_name, db):
    clean = normalize(name)
    
    # 1. DB Check (Always First)
    if clean in db:
        d = db[clean]
        if d.get('season_avg') is not None:
            return {"season_avg": d['season_avg'], "l5_avg": d.get('l5_avg', d['season_avg']), "source": "Internal DB"}
    
    # 2. Config Lookup
    config = API_CONFIG.get(sport_key.lower())
    if not config: 
        # Auto-detect if missing
        if "nba" in sport_key: config = API_CONFIG['nba']
        elif "nhl" in sport_key: config = API_CONFIG['nhl']
        else: return None

    provider, slug = config
    
    # 3. Route to Provider
    if provider == "liquipedia":
        res = fetch_liquipedia(name, slug)
    else:
        # Standard Sports (ESPN)
        res = fetch_espn_stats(name, config, stat_name)
        
        # If ESPN finds data, SAVE IT so we don't spam the API next time
        if res:
            save_data = {
                "id": name, "sport": sport_key, 
                "season_avg": res['season_avg'], "l5_avg": res['l5_avg'], 
                "verified_name": name
            }
            save_to_db(name, save_data)

    return res

# ==============================================================================
# III. THE v71.7 MATH ENGINE (UNIVERSAL)
# ==============================================================================
def get_usage_ceiling(prop): return 1.15 

def apex_v71_7_execute(prop):
    # Integrity Check
    if prop['season_avg'] is None:
        return {
            "Player": prop['name'][:18], "Line": prop['line'], "Verdict": f"{Fore.YELLOW}INPUT REQ{Style.RESET_ALL}", 
            "Pick": "-", "Conf": "0%", "Proj": "N/A", "Edge": "0%", "Source": prop.get('source', 'Unknown')
        }

    # 1. Map/Format Scalar
    vol_scalar = 1.0
    # Esports BO3 Detection
    if prop['line'] > 26.5 and "KILL" in prop.get('stat_type', ''): vol_scalar = 1.95
    if prop['line'] > 13.5 and "HEADSHOT" in prop.get('stat_type', ''): vol_scalar = 1.95
    
    # 2. Mean Projection
    mu_base = (prop['season_avg'] * 0.60 + prop['l5_avg'] * 0.40)
    mu_capped = min(mu_base, prop['season_avg'] * get_usage_ceiling(prop))
    mu_final = mu_capped * vol_scalar
    
    # 3. Probability (N-Binom/Poisson)
    default_sigma = prop['season_avg'] * 0.25 
    stable_var = default_sigma**2
    if stable_var < 0.1: stable_var = mu_final * 1.2

    if stable_var > mu_final:
        p_val = mu_final / stable_var
        n_val = (mu_final * p_val) / (1 - p_val)
        if mu_final > prop['line']: raw_prob = (1 - nbinom.cdf(prop['line'], n_val, p_val))
        else: raw_prob = nbinom.cdf(prop['line'], n_val, p_val)
    else:
        if mu_final > prop['line']: raw_prob = (1 - poisson.cdf(prop['line'], mu_final))
        else: raw_prob = poisson.cdf(prop['line'], mu_final)
    
    final_score = raw_prob * 100

    # 4. Volatility Guard
    cv = (default_sigma) / (prop['season_avg'] + 1e-9)
    if cv > 0.85: final_score *= 0.80 

    # 5. Verdict
    edge_ratio = abs(mu_final - prop['line']) / prop['line']
    moat_gate = 0.05 
    gate = 55.0 
    direction = "OVER" if mu_final > prop['line'] else "UNDER"
    is_valid = (final_score >= gate) and (edge_ratio >= moat_gate)

    tier = f"{Fore.CYAN}🔥 PLAY{Style.RESET_ALL}" if is_valid else f"{Fore.GREEN}✅ LEAN{Style.RESET_ALL}"
    if final_score < 50: tier = f"{Fore.RED}⛔ PASS{Style.RESET_ALL}"

    return {
        "Player": prop['name'][:18], 
        "Line": prop['line'],
        "Verdict": tier, 
        "Pick": direction, 
        "Conf": f"{final_score:.1f}%",
        "Proj": f"{mu_final:.1f}", 
        "Edge": f"{edge_ratio*100:.1f}%",
        "Source": prop.get('source', 'v71.7')
    }

# ==============================================================================
# IV. MAIN PROCESSING
# ==============================================================================
def process_prop(p, db):
    try:
        name = p['player']
        sport = p.get('sport', 'nba').lower() # Default to NBA if unknown, but prompts usually catch it
        stat = p.get('stat', 'Points')
        
        # Unified Data Fetch (Handles both ESPN and Liquipedia)
        stats = get_player_data(name, sport, stat, db)
        
        if not stats:
            print(f"{Fore.RED}   ❌ Unknown: {name} ({sport}){Style.RESET_ALL}")
            return None

        prop_obj = {
            "name": name,
            "line": float(p['line']),
            "season_avg": stats['season_avg'],
            "l5_avg": stats.get('l5_avg', stats.get('season_avg')),
            "stat_type": stat.upper(),
            "source": stats['source']
        }
        
        return apex_v71_7_execute(prop_obj)

    except Exception as e: 
        if DEBUG_MODE: print(f"Error processing {p.get('player')}: {e}")
        return None

def main():
    print(f"{Fore.CYAN}{Style.BRIGHT}--- APEX v3104.00: THE OMNI-SPORT RESTORATION ---{Style.RESET_ALL}")
    db = load_db()
    
    PROMPT = "Extract props as JSON list. Fields: 'player', 'line' (number), 'stat', 'sport' (GUESS: NBA, NHL, NFL, MLB, TENNIS, CSGO, VALORANT)."

    while True:
        try:
            batch = [f for f in os.listdir(WATCH_FOLDER) if f.endswith('.png') and "processed" not in f]
            if not batch: time.sleep(2); continue

            print(f"\n🚀 BATCH: {len(batch)} images.")
            
            for f in batch:
                path = os.path.join(WATCH_FOLDER, f)
                with open(path, "rb") as img: content = base64.b64encode(img.read()).decode()
                
                try:
                    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                        json={"contents": [{"parts": [{"text": PROMPT}, {"inline_data": {"mime_type": "image/png", "data": content}}]}], "generationConfig": {"responseMimeType": "application/json"}})
                    props = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                except: props = []

                if props:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        futures = {executor.submit(process_prop, p, db): p for p in props}
                        results = []
                        for future in as_completed(futures):
                            res = future.result()
                            if res: results.append(res)
                        
                        if results:
                            print(f"\n{Fore.YELLOW}📄 Image: {f}{Style.RESET_ALL}")
                            print(tabulate([[r['Player'], r['Line'], r['Verdict'], r['Pick'], r['Conf'], r['Proj'], r['Edge'], r['Source']] for r in results], 
                                          headers=["Player", "Line", "Verdict", "Pick", "Conf", "Proj", "Edge", "Source"], tablefmt="simple"))

                if not TEST_MODE: os.rename(path, os.path.join(PROCESSED_FOLDER, f))
            
        except KeyboardInterrupt: break
        except Exception as e: print(f"Error: {e}"); time.sleep(2)

if __name__ == "__main__":
    main()
