import re
import logging

logger = logging.getLogger(__name__)

_PII_PATTERNS = [
    (r'\b\d{10,}\b', '[TELEPHONE]'),
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP_ADDRESS]'),
    (r'\b(?:CI|SN|ML|BF|GN|TG|BJ|NE|CM|CG|CD|GA|MR|GW|ST|CV|KM|MG|MU|MZ|AO|ZA|NG|GH|KE|ET|EG|DZ|MA|TN|LY|SD|SO|UG|TZ|RW|BI|MW|ZM|ZW|LS|SZ|NA|BW|MZ|SC|RE|YT|PM|TF|BV|HM|CC|CX|NF|SH|AC|TA|IO|FK|GS|AQ)\d{9,}\b', '[ID_NATIONAL]'),
]


class DataShield:
    """
    Anonymise les données sensibles avant envoi à un LLM externe.
    Niveau MVP : patterns regex simples. Phase 2 : NER model.
    """

    def anonymize(self, text: str) -> str:
        for pattern, replacement in _PII_PATTERNS:
            text = re.sub(pattern, replacement, text)
        return text

    def is_sensitive(self, text: str) -> bool:
        for pattern, _ in _PII_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    def sanitize_for_log(self, text: str, max_length: int = 200) -> str:
        anonymized = self.anonymize(text)
        return anonymized[:max_length] + "..." if len(anonymized) > max_length else anonymized
