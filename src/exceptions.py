class AmbiguousNameError(Exception):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__(f"Ambiguous name: {candidates}")
