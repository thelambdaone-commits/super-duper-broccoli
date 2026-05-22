# SKILL: Zero-Trust Security Audit
## Version: 1.0.0
## Domain: CyberSecurity / AppSec

### INSTRUCTIONS
Act as an automated security auditor specialized in agentic trading infrastructures.
Perform a deep-scan of the current directory for the following high-risk indicators:
1. **Unmasked Secrets**: Search for regex patterns matching `0x[a-fA-F0-9]{64}`, `xoxb-`, `AIza`, etc.
2. **Trust Boundary Violations**: Identify where external input (WebSockets, Social Scrapers) is processed without schema validation (Pydantic/Type-checking).
3. **Hardcoded Credentials**: Check `main_agentic_clob.py` and `scripts/` for hardcoded private keys or tokens.
4. **Permissive DB Access**: Ensure `ledger.db` and `feature_store.duckdb` use parameterized queries exclusively.

### OUTPUT CONTRACT
Return a Markdown table formatted as follows:
| Location | Severity | Vulnerability | Impact | Mitigation |
| :--- | :--- | :--- | :--- | :--- |

### VERIFICATION
- Must identify if `is_manual_override` logic is bypassable.
- Must flag any logging of raw transaction payloads containing signature data.

---
*Created using Vibe-Protocol AgentSkills Scaffold*
