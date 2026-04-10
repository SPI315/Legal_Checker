class PolicyValidator:
    def ensure_external_analysis_allowed(self, anonymized_text: str) -> None:
        if not anonymized_text.strip():
            raise ValueError("policy_blocked: anonymized_text is empty")
