"""Objection handling placeholder."""


class ObjectionHandler:
    """Map objections to scripted responses until the real workflow lands."""

    def handle(self, text: str) -> str:
        if "don't believe" in text.lower():
            return "I can share more detail or connect you with a human agent."
        return ""

