from __future__ import annotations

# ── Port → service name labels ────────────────────────────────────────────────
# Shown in the LISTEN PORTS table "Name / Service" column.
PORT_LABELS: dict[int, str] = {
    # Web / proxy
    80:    "HTTP",
    443:   "HTTPS",
    8080:  "HTTP Alt",
    8443:  "HTTPS Alt",
    8888:  "Jupyter",
    # Dev servers
    3000:  "Dev (Node)",
    3001:  "Dev Alt",
    4200:  "Angular",
    5173:  "Vite",
    5000:  "Flask / Dev",
    8000:  "Python Dev",
    8001:  "Dev Alt",
    8081:  "Dev Alt",
    35729: "LiveReload",
    # Databases
    3306:  "MySQL",
    5432:  "PostgreSQL",
    6379:  "Redis",
    27017: "MongoDB",
    9200:  "Elasticsearch",
    5601:  "Kibana",
    8086:  "InfluxDB",
    # Message brokers
    5672:  "RabbitMQ",
    15672: "RabbitMQ UI",
    9092:  "Kafka",
    1883:  "MQTT",
    8883:  "MQTT TLS",
    # AI / LLM services
    11434: "Ollama",
    1234:  "LM Studio",
    5001:  "Text Gen WebUI",
    4891:  "GPT4All",
    # Other common services
    22:    "SSH",
    21:    "FTP",
    25:    "SMTP",
    587:   "SMTP TLS",
    993:   "IMAP TLS",
    5900:  "VNC",
}

# ── Polling intervals (seconds) ───────────────────────────────────────────────
POLL_INTERVAL        = 2.0
DOCKER_POLL_INTERVAL = 3.0
HEROKU_POLL_INTERVAL = 3600.0  # Heroku API rate limits — load on startup + hourly
SYSMETRICS_INTERVAL  = 1.0
SYSMETRICS_HISTORY   = 120     # samples retained (~2 min at 1 s)

# ── AI / Agent detection ──────────────────────────────────────────────────────
# (pattern_substring, display_label) — matched against lowercased full command.
# Order matters: first match wins.
AI_PROCESS_PATTERNS: list[tuple[str, str]] = [
    ("claude.app",      "Claude Desktop"),
    ("claude",          "Claude CLI"),
    ("ollama",          "Ollama"),
    ("llama",           "Llama"),
    ("lm studio",       "LM Studio"),
    ("openai",          "OpenAI"),
    ("anthropic",       "Anthropic"),
    ("litellm",         "LiteLLM"),
    ("langchain",       "LangChain"),
    ("langserve",       "LangServe"),
    ("autogen",         "AutoGen"),
    ("crewai",          "CrewAI"),
    ("agentops",        "AgentOps"),
    ("copilot",         "Copilot"),
]

# Ports that indicate a running AI service (checked via lsof separately)
AI_SERVICE_PORTS: dict[int, str] = {
    11434: "Ollama",
    1234:  "LM Studio",
    5001:  "Text Gen WebUI",
    4891:  "GPT4All",
}
