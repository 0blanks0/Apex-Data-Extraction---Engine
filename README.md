# APEX: LLM-Driven Data Extraction Engine

## Overview
APEX is a dual-engine, multimodal data pipeline built through complex "vibe coding" and iterative LLM prompting (Gemini 2.0 Flash API). It is designed to autonomously process raw visual inputs, extract complex statistical data, and dynamically route requests across multiple rate-limited APIs to build a cohesive mathematical projection for pregame and halftime analysis. 

This project was built to test the limits of LLM code generation, actively overcoming narrative drift and hallucination through strict prompt guardrails, while engineering workarounds for the high costs of traditional sports data APIs.

## Core Architecture
* **Multimodal Data Extraction:** Uses specific prompt engineering to force the AI to read, categorize (e.g., color-coded promos), and structure raw image data into clean JSON formats.
* **API Resource Management:** Intentionally designed to bypass exorbitant live-feed API costs by programmatically extracting and compiling historical game-log and pregame data from accessible endpoints (ESPN, NHL Edge, Liquipedia).
* **Dynamic API Routing:** Automatically categorizes entities (traditional sports vs. esports) and routes requests to the appropriate data sources.
* **Advanced Data Sanitization:** Employs RegEx and heuristic fallback logic to normalize unpredictable web scraping returns and clean messy data strings.
* **Concurrency & Mathematics:** Uses `ThreadPoolExecutor` for high-speed multi-threading and `scipy.stats` (Poisson/Negative Binomial) for statistical modeling.

## Technical Stack
* **Language:** Python
* **AI/LLM:** Gemini 2.0 Flash
* **Libraries:** `requests`, `numpy`, `scipy`, `concurrent.futures`, `re`, `json`, `base64`
* 
