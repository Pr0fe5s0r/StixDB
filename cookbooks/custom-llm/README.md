# Custom LLM Cookbooks

Comprehensive examples of using different LLM providers and strategies with StixDB for various use cases.

## Included Cookbooks

### 1. **anthropic.py** — Anthropic Claude
Use Claude models for reasoning and memory management.
- Models: Claude Opus 4.6, Claude 3.5 Sonnet, Claude 3 Haiku
- Best for: Complex reasoning, multi-step analysis, premium quality
- Cost: Higher, but most capable
- Use case: Enterprise applications needing best quality

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python anthropic.py
```

---

### 2. **ollama_local.py** — Local LLMs via Ollama
Run LLMs completely locally for privacy and offline use.
- Models: Llama2, Mistral, Neural Chat, Dolphin
- Best for: Privacy, offline, regulated environments
- Cost: Free (hardware only)
- Use case: HIPAA, confidential data, no internet

```bash
ollama serve
# in another terminal:
ollama pull mistral
python ollama_local.py
```

---

### 3. **openai_gpt4o.py** — OpenAI GPT-4o (Cost-Optimized)
Fast, cost-effective reasoning with OpenAI's latest models.
- Models: GPT-4o (balanced), GPT-4 Turbo (powerful), GPT-3.5 Turbo (budget)
- Best for: Cost-conscious, high-volume, real-time applications
- Cost: Middle ground, very fast
- Use case: Customer support, chatbots, production APIs

```bash
export OPENAI_API_KEY=sk-...
python openai_gpt4o.py
```

---

### 4. **privacy_first_local_llm.py** — Privacy-First Local LLM (Ollama)
Completely private inference for sensitive data.
- Models: Mistral 7B, Llama2 13B, Neural Chat
- Best for: HIPAA, GDPR, confidential workloads
- Cost: Zero API fees
- Use case: Healthcare, legal, regulated industries

```bash
ollama serve
python privacy_first_local_llm.py
```

---

### 5. **multi_model_routing.py** — Intelligent Model Selection
Route queries to different models based on complexity for cost optimization.
- Strategy: Simple → GPT-3.5, Standard → GPT-4o, Complex → Claude Opus
- Best for: Mixed workloads, cost optimization, A/B testing
- Cost: Optimal (pay for what you need)
- Use case: SaaS platforms, large-scale applications

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
python multi_model_routing.py
```

---

## Quick Comparison

| Provider | Model | Speed | Cost | Quality | Privacy |
|----------|-------|-------|------|---------|---------|
| **Anthropic** | Claude Opus | Medium | $$$ | ⭐⭐⭐⭐⭐ | Cloud |
| **OpenAI** | GPT-4o | Fast | $$ | ⭐⭐⭐⭐ | Cloud |
| **OpenAI** | GPT-4 Turbo | Medium | $$$ | ⭐⭐⭐⭐⭐ | Cloud |
| **OpenAI** | GPT-3.5 Turbo | Very Fast | $ | ⭐⭐⭐ | Cloud |
| **Local** | Mistral 7B | Slow | Free | ⭐⭐⭐ | Private |
| **Local** | Llama2 13B | Slower | Free | ⭐⭐⭐⭐ | Private |

---

## Choosing the Right LLM

### For Quality (Best Reasoning)
→ **Claude Opus** or **GPT-4 Turbo**
- Complex multi-step reasoning
- Enterprise decision-making
- Technical analysis

### For Balance
→ **GPT-4o**
- Good quality at reasonable cost
- Most versatile
- Production workhorse

### For Cost
→ **GPT-3.5 Turbo** or **Multi-Model Routing**
- Simple queries
- High volume
- Tight budget

### For Privacy
→ **Local LLM (Ollama)** or **On-Premises**
- HIPAA/GDPR compliance
- Sensitive data
- Offline capability
- Zero API cost

### For Speed
→ **GPT-3.5 Turbo** or **GPT-4o**
- Real-time chat
- Low-latency API
- User-facing applications

---

## Common Patterns

### Pattern 1: Cost-Optimized Production
```python
# Use routing to optimize cost
from cookbooks.custom_llm.multi_model_routing import classify_query_complexity

if classify_query_complexity(user_question) == "simple":
    use_gpt_35_turbo()
elif classify_query_complexity(user_question) == "complex":
    use_claude_opus()
else:
    use_gpt4o()
```

### Pattern 2: Privacy-First Enterprise
```python
# Use local LLM for sensitive data
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import ReasonerConfig, LLMProvider

config = StixDBConfig(
    reasoner=ReasonerConfig(
        provider=LLMProvider.OLLAMA,
        model="mistral:7b",
        ollama_base_url="http://localhost:11434"
    )
)

engine = StixDBEngine(config)
# No data sent to APIs
```

### Pattern 3: Hybrid (Cloud + Local Fallback)
```python
# Try cloud first, fall back to local if needed
try:
    result = await engine_gpt4o.ask(...)  # Fast, reliable
except Exception:
    result = await engine_local.ask(...)  # Fallback
```

---

## Setup Instructions

### For Cloud LLMs (OpenAI, Anthropic)
1. Get API keys from provider
2. Export environment variables:
   ```bash
   export OPENAI_API_KEY=sk-...
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Install SDK:
   ```bash
   pip install "stixdb-engine[local-dev]"
   ```

### For Local LLMs (Ollama)
1. Install Ollama: https://ollama.ai
2. Start Ollama:
   ```bash
   ollama serve
   ```
3. Pull models:
   ```bash
   ollama pull mistral
   ollama pull llama2
   ```
4. Run cookbook:
   ```bash
   python ollama_local.py
   ```

---

## Performance Benchmarks

### Response Time (first token latency)
- GPT-3.5 Turbo: ~100ms (cloud)
- GPT-4o: ~300ms (cloud)
- GPT-4 Turbo: ~500ms (cloud)
- Claude Opus: ~800ms (cloud)
- Mistral 7B (local): ~2-5s (depends on GPU)
- Llama2 13B (local): ~5-10s (depends on GPU)

### Cost Per 1K Tokens
- GPT-3.5 Turbo: $0.0005
- GPT-4o: $0.003
- GPT-4 Turbo: $0.01
- Claude Opus: $0.015
- Local: $0 (after model download)

---

## Troubleshooting

### "API key not found"
- Ensure environment variable is set: `export OPENAI_API_KEY=sk-...`
- Check key is valid in provider's dashboard

### "Connection refused" (for Ollama)
- Start Ollama: `ollama serve`
- Check it's accessible: `curl http://localhost:11434/api/tags`

### "Model not found" (for Ollama)
- Pull the model: `ollama pull mistral`
- List available: `ollama ls`

### "Rate limited"
- Use multi-model routing to distribute load
- Implement request queuing
- Consider local fallback

---

## When to Use Each

**Use Claude Opus when:**
- Best possible quality needed
- Complex reasoning required
- You have budget for premium

**Use GPT-4o when:**
- Default choice
- Balance of quality and cost
- Most reliable option

**Use GPT-3.5 Turbo when:**
- Cost is priority
- Simple queries
- High volume

**Use Local LLM when:**
- Privacy critical
- Offline required
- No API budget
- Regulatory compliance needed

---

## Advanced Topics

### Multi-Model Strategies
See `multi_model_routing.py` for intelligent routing based on:
- Query complexity
- User tier (premium vs. free)
- Cost budgets
- Privacy requirements

### Fallback Chains
```python
# Try expensive model first, fall back to cheaper
models = [
    ("claude-opus", "cost-no-limit"),
    ("gpt-4o", "normal-cost"),
    ("mistral:7b", "local-free"),
]
```

### A/B Testing
- Compare model outputs on same queries
- Track user satisfaction
- Optimize model selection

---

## Related Resources

- [Anthropic API Documentation](https://docs.anthropic.com)
- [OpenAI API Documentation](https://platform.openai.com/docs)
- [Ollama Documentation](https://ollama.ai)
- [StixDB Configuration Guide](../../doc/)

---

## Contributing

Found a use case not covered? Submit a PR with a new cookbook!
