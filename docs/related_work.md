# MCPDrift - Related Work

## 1. Foundational Work: Indirect Prompt Injection

The field is grounded in **Greshake et al. (2023)**, *Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection* (arXiv:2302.12173, AISec 2023).

That paper formalized a class of attacks in which the adversary does not address the LLM directly. Instead, attacker instructions are embedded into data that the model later reads on its own: web pages, documents, email, or other external content. Once an agent consumes poisoned content, the malicious instruction enters the model context alongside the user request. The paper also framed the downstream consequences, including data theft, worm-like propagation between agents, contamination of the surrounding information ecosystem, and unauthorized API actions.

**Connection to MCPDrift:** MCPDrift studies a narrower but highly relevant variant of the same family: injection through *tool descriptions* rather than tool outputs or retrieved content. The attack lands before the first tool call, when the agent ingests the tool manifest.

---

## 2. Benchmarks for Agent Security

### AgentDojo (Debenedetti et al., NeurIPS 2024)

arXiv:2406.13352

AgentDojo is the most widely cited benchmark in the area. It evaluates adversarial behavior in a dynamic environment with 97 user tasks and 629 adversarial scenarios. The attack is injected through *tool responses*. In the published setup, GPT-4o retains meaningful utility but suffers a clear drop under attack while attack success remains substantial.

**Connection to MCPDrift:** AgentDojo is the closest methodological relative. The key difference is the attack moment: AgentDojo injects via *tool results*, while MCPDrift injects via *tool descriptions*. Those are different trust boundaries and therefore imply different defenses. MCPDrift also emphasizes explicit multi-turn measurements such as latency of compromise and degradation rate, which AgentDojo does not foreground.

### InjecAgent (Zhan et al., 2024)

arXiv:2403.02691

InjecAgent is an early benchmark focused specifically on indirect prompt injection in tool-integrated agents. It includes 1,054 test cases across domains such as finance, smart home control, and email. Its emphasis is on isolated attack steps rather than end-to-end multi-turn environments.

**Connection to MCPDrift:** InjecAgent established that indirect prompt injection is practical across realistic tool-use domains. MCPDrift extends that direction toward MCP-specific attack surfaces and delayed multi-turn compromise.

---

## 3. MCP-Specific Work (2025-2026)

### MCP-38 Threat Taxonomy

arXiv:2603.18063

This work proposes a broad threat taxonomy for MCP systems, covering 38 attack classes. It explicitly includes tool description poisoning, indirect prompt injection, parasitic tool chaining, and dynamic trust violations. The taxonomy is aligned with STRIDE, OWASP LLM Top 10 (2025), and OWASP Agentic Top 10 (2026).

**Connection to MCPDrift:** MCPDrift empirically measures the subset of MCP-38 that concerns tool description poisoning. That makes MCPDrift a quantitative complement to the taxonomy.

### Are AI-assisted Development Tools Immune to Prompt Injection?

arXiv:2603.21642

This 2026 study evaluates real MCP clients such as Claude Desktop and Cursor against prompt-injection and tool-poisoning attacks. Its findings suggest that robustness varies substantially across client implementations.

**Connection to MCPDrift:** The topic overlaps directly, but the evaluation target differs. That work studies end-user MCP clients in realistic deployments. MCPDrift instead isolates model behavior from client-specific orchestration, making it easier to attribute observed failures to model-level susceptibility rather than product-level integration details.

### Unit 42 / Palo Alto Networks (December 2025)

#### New Prompt Injection Attack Vectors Through MCP Sampling

This work demonstrates practical attacks through MCP sampling features in coding-assistant settings.

### Simon Willison (April 2025)

#### Model Context Protocol has prompt injection security problems

This influential practitioner analysis helped crystallize the industry discussion around MCP prompt injection and popularized the "rug pull" intuition: a tool can appear safe at approval time and later abuse its own description.

### Invariant Labs (April 2025)

Invariant Labs publicly demonstrated a tool-poisoning attack against a WhatsApp MCP setup, where a seemingly harmless tool exfiltrated private message history. This was one of the clearest public examples of product-level MCP compromise.

---

## 4. OWASP Standards

### OWASP Top 10 for LLM Applications 2025

- `LLM01: Prompt Injection` is the direct parent category for MCPDrift scenarios.
- `LLM02: Insecure Tool Handling` captures the trust model behind tool-description poisoning.

### OWASP Top 10 for Agentic Applications 2026

- The emerging `ASI01-ASI10` taxonomy is relevant for mapping MCPDrift scenarios into agent-specific security language.

MCPDrift can be explicitly mapped onto these standards in benchmark reports and evaluation summaries.

---

## 5. Positioning MCPDrift in the Literature

| Criterion | Greshake 2023 | AgentDojo | InjecAgent | MCP-38 | MCPDrift |
| --- | --- | --- | --- | --- | --- |
| Attack vector | Tool outputs / external data | Tool outputs | Tool outputs | Taxonomy | **Tool descriptions** |
| Multi-turn | No | Partial | No | No | **Yes** |
| Latency metrics | No | No | No | No | **Yes** |
| Defense sweep | No | Yes | No | No | **Yes** |
| Real LLM comparison | No | Yes | Yes | No | **Yes** |
| MCP-specific | No | No | No | Yes | **Yes** |

**Gap closed by MCPDrift:** existing benchmarks do not directly measure robustness to attacks delivered through *tool descriptions* in *multi-turn* sessions with explicit delayed-compromise metrics. That is the niche MCPDrift is designed to fill.

---

## Key References

```text
Greshake et al., "Not What You've Signed Up For", AISec 2023, arXiv:2302.12173
Debenedetti et al., "AgentDojo", NeurIPS 2024, arXiv:2406.13352
Zhan et al., "InjecAgent", 2024, arXiv:2403.02691
MCP-38 Threat Taxonomy, arXiv:2603.18063
"Are AI-assisted Development Tools Immune to Prompt Injection?", arXiv:2603.21642
OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org
```
