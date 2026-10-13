class ClassifierUnavailableError(Exception):
    """A classifier could not answer (rate limited, network down, bad credentials)."""

    def __init__(self, classifier: str, reason: str):
        self.classifier = classifier
        self.reason = reason
        super().__init__(f"{classifier} unavailable: {reason}")


class SourceUnavailableError(Exception):
    """A recipe or offer source could not be reached."""

    def __init__(self, source: str, reason: str):
        self.source = source
        self.reason = reason
        super().__init__(f"Could not reach {source}: {reason}")
