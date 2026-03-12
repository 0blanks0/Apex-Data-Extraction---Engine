# ==============================================================================
# APEX v3311.00: THE GOLD MASTER (PERFECT STATS + PROMO VISION)
# ==============================================================================
# 1. ACCURACY: Uses NHL Realtime API for Hits/Blocks (Fixes 0s).
# 2. VISION: Restored detailed prompt to detect DEMON/TACO/GOBLIN variants.
# 3. STABILITY: Uses 'hardcoded_players.json' to prevent Unknowns.
# 4. LOGIC: Applies strict "No Under on Demons" rules using the restored vision.
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
MAX_WORKERS = 1
CURRENT_NHL_SEASON = "20252026"

BASE_DIR = r"C:\Users\erikr\bot proj"
WATCH_FOLDER = os.path.join(BASE_DIR, "screenshots")
PROCESSED_FOLDER = os.path.join(WATCH_FOLDER, "processed")
CACHE_FILE = os.path.join(BASE_DIR, "players.json")
VAULT_FILE = os.path.join(BASE_DIR, "hardcoded_players.json")

# --- API KEYS ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LIQUIPEDIA_KEY = os.getenv("LIQUIPEDIA_KEY") 

if not GEMINI_API_KEY: sys.exit("❌ ERROR: Missing GEMINI_API_KEY")

# --- SPORT ROUTING ---
API_CONFIG = {
    "nba": ("basketball", "nba"), "nfl": ("football", "nfl"),
    "mlb": ("baseball", "mlb"), "nhl": ("hockey", "nhl"), 
    "csgo": ("liquipedia", "counterstrike"), "valorant": ("liquipedia", "valorant"),
    "lol": ("liquipedia", "leagueoflegends")
}

# --- DEFAULT VAULT ---
DEFAULT_VAULT_DATA = {
    "mitch marner": "8478483", "mitchell marner": "8478483",
    "travis sanheim": "8477948", "mathew barzal": "8478445",
    "sebastian aho": "8478427", "connor mcdavid": "8478402",
    "nathan mackinnon": "8477492", "alex steeves": "8482634",
    "kiefer sherwood": "8480748", "sean couturier": "8476461",
    "evan bouchard": "8480803", "jason robertson": "8480027",
    "sam reinhart": "8477933", "jacob trouba": "8476885",
    "brad marchand": "8473419", "artturi lehkonen": "8477476"
}

NHL_ALIASES = {
    "alex debrincat": "alexander debrincat", "jt miller": "j.t. miller",
    "tj oshie": "t.j. oshie", "max domi": "max domi",
    "zach hyman": "zachary hyman", "pat maroon": "patrick maroon",
    "josh morrissey": "joshua morrissey"
}

init(autoreset=True)
try:
    from tabulate import tabulate
except ImportError:
    def tabulate(data, headers, tablefmt): return str(data)

if not os.path.exists(WATCH_FOLDER): os.makedirs(WATCH_FOLDER)
if not os.path.exists(PROCESSED_FOLDER): os.makedirs(PROCESSED_FOLDER)

# --- INIT VAULT ---
if os.path.exists(CACHE_FILE):
    try: os.remove(CACHE_FILE)
    except: pass

def load_vault():
    if not os.path.exists(VAULT_FILE):
        try:
            with open(VAULT_FILE, 'w') as f: json.dump(DEFAULT_VAULT_DATA, f, indent=4)
            return DEFAULT_VAULT_DATA
        except: return DEFAULT_VAULT_DATA
    else:
        try:
            with open(VAULT_FILE, 'r') as f: return json.load(f)
        except: return DEFAULT_VAULT_DATA

PERMANENT_ID_MAP = load_vault()

def log(msg, type="INFO"):
    if DEBUG_MODE:
        colors = {"ERROR": Fore.RED, "SUCCESS": Fore.GREEN, "WARN": Fore.YELLOW, "NET": Fore.BLUE}
        print(f"{colors.get(type, Fore.WHITE)}[{type}] {msg}{Style.RESET_ALL}")

# ==============================================================================
# I. DATABASE
# ==============================================================================
def normalize(name): return re.sub(r'[^a-z0-9]', '', name.lower())

def load_db():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_to_db(name, data):
    current_db = load_db()
    key = normalize(name)
    current_db[key] = {
        "id": data.get('id'), "sport": data.get('sport'),
        "verified_name": data.get('verified_name', name),
        "source": data.get('source', 'Unknown')
    }
    try:
        with open(CACHE_FILE, 'w') as f: json.dump(current_db, f, indent=4)
    except: pass

# ==============================================================================
# II. DATA FETCHERS
# ==============================================================================

# --- A. NHL SPECIFIC (ROUTER) ---
def parse_toi(toi_str):
    try:
        if ":" in str(toi_str):
            m, s = map(int, toi_str.split(":"))
            return m + (s / 60.0)
        return float(toi_str)
    except: return 0.0

def fetch_nhl_id(player_name):
    lower = player_name.lower()
    if lower in PERMANENT_ID_MAP: return PERMANENT_ID_MAP[lower]
    
    search_name = NHL_ALIASES.get(lower, player_name)
    log(f"NHL: Searching ID for '{search_name}'...", "NET")
    
    try:
        url = f"https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=20&q={search_name}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data:
                slug = normalize(search_name)
                for p in data:
                    if slug in normalize(p.get('name', '')):
                        return p.get('playerId')
                return data[0].get('playerId')
    except: pass
    return None

# --- NEW: PHYSICAL STATS FETCHER (HITS/BLOCKS) ---
def fetch_nhl_realtime_stats(pid, player_name, stat_name):
    try:
        url = f"https://api.nhle.com/stats/rest/en/skater/realtime?isAggregate=false&isGame=true&sort=[{{%22property%22:%22gameDate%22,%22direction%22:%22DESC%22}}]&cayenneExp=playerId={pid}%20and%20gameTypeId=2%20and%20seasonId={CURRENT_NHL_SEASON}&limit=5"
        
        log(f"NHL: Fetching Realtime Stats (Hits/Blocks) for {player_name}", "NET")
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        
        if r.status_code == 200:
            data = r.json()
            games = data.get('data', [])
            raw_stats = []
            s_upper = stat_name.upper()
            
            for g in games:
                val = 0.0
                if "HIT" in s_upper: val = float(g.get('hits', 0))
                elif "BLOCK" in s_upper: val = float(g.get('blockedShots', 0))
                else: val = 0.0
                raw_stats.append(val)
                
            if raw_stats:
                return {"season_avg": np.mean(raw_stats), "l5_raw": raw_stats, "source": "NHL Realtime"}
                
    except Exception as e:
        log(f"NHL Realtime Error: {e}", "ERROR")
    return None

# --- STANDARD NHL FETCHER ---
def fetch_nhl_stats(player_name, stat_name):
    pid = fetch_nhl_id(player_name)
    if not pid: return None
    
    # ROUTING
    s_upper = stat_name.upper()
    if "HIT" in s_upper or "BLOCK" in s_upper:
        return fetch_nhl_realtime_stats(pid, player_name, stat_name)

    try:
        url = f"https://api-web.nhle.com/v1/player/{pid}/game-log/now"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            games = r.json().get('gameLog', [])[:5]
            raw_stats = []
            for g in games:
                val = 0.0
                if "GOAL" in s_upper: val = float(g.get('goals', 0))
                elif "ASSIST" in s_upper: val = float(g.get('assists', 0))
                elif "POINT" in s_upper: val = float(g.get('points', 0))
                elif "SOG" in s_upper or "SHOT" in s_upper: val = float(g.get('shots', 0))
                elif "TIME" in s_upper or "TOI" in s_upper: 
                    val = parse_toi(g.get('toi', g.get('timeOnIce', '0:00')))
                else: val = float(g.get('points', 0))
                raw_stats.append(val)
            
            if raw_stats:
                save_to_db(player_name, {"id": pid, "sport": "nhl", "source": "NHL Edge"})
                return {"season_avg": np.mean(raw_stats), "l5_raw": raw_stats, "source": "NHL Edge"}
    except: pass
    return None

# --- B. ESPORTS ---
def fetch_liquipedia(player_name, wiki_slug):
    if not LIQUIPEDIA_KEY: return {"season_avg": 0, "l5_raw": [], "source": "No Key"}
    url = f"https://api.liquipedia.net/api/v3/{wiki_slug}/search"
    headers = {"Authorization": f"Apikey {LIQUIPEDIA_KEY}", "User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, params={"wiki": wiki_slug, "limit": 1, "q": player_name}, timeout=3)
        if r.status_code == 200: return {"season_avg": None, "source": f"Liquipedia ({wiki_slug})"}
    except: pass
    return None

# --- C. ESPN ---
def fetch_espn_stats(player_name, sport_tuple, stat_name):
    sport, league = sport_tuple
    clean_name = re.split(r'\s+(vs|@)\s+', player_name, flags=re.IGNORECASE)[0].strip()
    log(f"ESPN: Searching {clean_name}...", "NET")
    try:
        url = f"https://site.web.api.espn.com/apis/common/v3/search?region=us&lang=en&query={clean_name}&limit=1&mode=prefix&type=player&sport={sport}&league={league}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        data = r.json()
        if not data.get('items'): return None
        pid = data['items'][0]['id']
        
        raw_stats = []
        for season in ["2026", "2025"]:
            if len(raw_stats) >= 5: break
            log_url = f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{pid}/gamelog?season={season}"
            r = requests.get(log_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if r.status_code == 200:
                log_data = r.json()
                if 'seasonTypes' in log_data:
                    for st in log_data['seasonTypes']:
                        for cat in st.get('categories', []):
                            for e in cat.get('events', []):
                                s_upper = stat_name.upper()
                                stats = e.get('stats', [])
                                if not stats: continue
                                val = 0.0
                                try:
                                    if league == "nba":
                                        if "POINT" in s_upper: val = float(stats[-1])
                                        elif "REBOUND" in s_upper: val = float(stats[-7])
                                        elif "ASSIST" in s_upper: val = float(stats[-6])
                                        elif "PRA" in s_upper: val = float(stats[-1]) + float(stats[-7]) + float(stats[-6])
                                        else: val = float(stats[-1])
                                    else: val = float(stats[0])
                                    if val >= 0: raw_stats.append(val)
                                except: pass
        if raw_stats:
            save_to_db(clean_name, {"id": pid, "sport": league, "source": "ESPN"})
            return {"season_avg": np.mean(raw_stats), "l5_raw": raw_stats[:5], "source": f"ESPN ({league.upper()})"}
    except: pass
    return None

# --- D. ROUTER ---
def get_player_data(name, sport_key, stat_name, db):
    sport_key = sport_key.lower()
    if "nhl" in sport_key or "hockey" in sport_key: return fetch_nhl_stats(name, stat_name)
    
    config = API_CONFIG.get(sport_key)
    if not config:
        if "nba" in sport_key: config = API_CONFIG['nba']
        elif "nfl" in sport_key: config = API_CONFIG['nfl']
        elif "cs" in sport_key: config = API_CONFIG['csgo']
        else: return None

    provider, slug = config
    if provider == "liquipedia": return fetch_liquipedia(name, slug)
    return fetch_espn_stats(name, config, stat_name)

# ==============================================================================
# III. MATH ENGINE
# ==============================================================================
def get_usage_ceiling(prop): return 1.15 

def apex_v71_7_execute(prop):
    if prop['season_avg'] is None:
        return {
            "Player": prop['name'][:18], "Line": prop['line'], "Stat": prop['stat_type'], "Type": prop.get('variant', 'BASE'),
            "Verdict": f"{Fore.RED}UNKNOWN{Style.RESET_ALL}", "Pick": "-", "Conf": "0%", "Proj": "N/A", "L5": "-", "Avg": "-", "Source": "Not Found"
        }

    vol_scalar = 1.0
    variant = prop.get('variant', 'BASE').upper()
    l5_raw = prop.get('l5_raw', [])
    l5_avg = np.mean(l5_raw) if l5_raw else prop['season_avg']

    mu_base = (prop['season_avg'] * 0.50 + l5_avg * 0.50) 
    mu_final = mu_base * vol_scalar
    
    if mu_final > prop['line']: 
        raw_prob = (1 - poisson.cdf(prop['line'], mu_final))
    else: 
        raw_prob = poisson.cdf(prop['line'], mu_final)
    
    final_score = raw_prob * 100
    if len(l5_raw) < 2: final_score *= 0.5
    
    direction = "OVER" if mu_final > prop['line'] else "UNDER"
    is_promo = any(x in variant for x in ["DEMON", "GOBLIN", "TACO", "DISCOUNT"])
    
    if is_promo and direction == "UNDER":
        return {
            "Player": prop['name'][:18], "Line": prop['line'], "Stat": prop['stat_type'][:10], "Type": variant,
            "Verdict": f"{Fore.RED}⛔ DENY{Style.RESET_ALL}", "Pick": "PASS", "Conf": f"{final_score:.1f}%", 
            "Proj": f"{mu_final:.1f}", "L5": str(l5_raw), "Avg": f"{prop['season_avg']:.1f}", "Source": "Logic Check"
        }
    
    if final_score >= 90.0: tier = f"{Fore.CYAN}💎 DIAMOND{Style.RESET_ALL}"
    elif final_score >= 75.0: tier = f"{Fore.GREEN}🔥 PLAY{Style.RESET_ALL}"
    elif final_score >= 55.0: tier = f"{Fore.GREEN}✅ LEAN{Style.RESET_ALL}"
    else: tier = f"{Fore.RED}⛔ PASS{Style.RESET_ALL}"

    l5_str = str([int(x) if x.is_integer() else round(x,1) for x in l5_raw])
    if len(l5_str) > 20: l5_str = l5_str[:18] + "..]"

    return {
        "Player": prop['name'][:18], "Line": prop['line'], "Stat": prop['stat_type'][:10], "Type": variant,
        "Verdict": tier, "Pick": direction, "Conf": f"{final_score:.1f}%", 
        "Proj": f"{mu_final:.1f}", "L5": l5_str, "Avg": f"{prop['season_avg']:.1f}", "Source": prop.get('source', 'Engine')
    }

# ==============================================================================
# IV. MAIN
# ==============================================================================
def process_prop(p, db):
    try:
        name = p['player']
        sport = p.get('sport', 'nba').lower() 
        if "nhl" in sport or "hockey" in sport: sport = "nhl"
        
        stat = p.get('stat', 'Points') 
        variant = p.get('variant', 'BASE')
        
        stats = get_player_data(name, sport, stat, db)
        if not stats:
            return {"Player": name, "Verdict": f"{Fore.RED}UNKNOWN{Style.RESET_ALL}", "Pick": "-", "Conf": "0%", "Proj": "0", "L5": "-", "Avg": "-", "Source": "Not Found", "Line": p['line'], "Stat": stat, "Type": variant}

        prop_obj = {
            "name": name, "line": float(p['line']), "season_avg": stats['season_avg'],
            "l5_raw": stats.get('l5_raw', []), "stat_type": stat, "variant": variant, "source": stats['source']
        }
        return apex_v71_7_execute(prop_obj)
    except: return None

def main():
    print(f"{Fore.CYAN}{Style.BRIGHT}--- APEX v3311.00: THE GOLD MASTER ---{Style.RESET_ALL}")
    
    global PERMANENT_ID_MAP
    PERMANENT_ID_MAP = load_vault()
    db = load_db()
    
    # DETAILED PROMPT RESTORED FOR PROMO DETECTION
    PROMPT = """
    Extract betting props as a JSON list.
    Fields:
    - 'player': Name.
    - 'line': Betting Line (CRITICAL: Ignore crossed-out numbers. Get the COLORED number. Decimals allowed).
    - 'stat': Stat name.
    - 'sport': Sport (NBA, NHL, CSGO).
    - 'variant': 
        * RED/ORANGE DEVIL = "DEMON"
        * GREEN SLIME/MONSTER = "GOBLIN"
        * YELLOW/ORANGE FOOD/TACO = "TACO"
        * WHITE/GREY/NONE = "BASE"
    """

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
                            print(tabulate([[r['Player'], r['Line'], r['Stat'], r['Type'], r['Verdict'], r['Pick'], r['Conf'], r['Proj'], r['L5'], r['Avg'], r['Source']] for r in results], 
                                          headers=["Player", "Line", "Stat", "Type", "Verdict", "Pick", "Conf", "Proj", "L5", "Avg", "Source"], tablefmt="simple"))

                if not TEST_MODE: os.rename(path, os.path.join(PROCESSED_FOLDER, f))
        except KeyboardInterrupt: break
        except Exception as e: print(f"Error: {e}"); time.sleep(2)

if __name__ == "__main__":
    main()
