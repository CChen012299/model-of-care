class RulesConfigError(ValueError):
    """Raised at load time when a rules YAML file is invalid.

    Rules are validated when the catalog loads, not when a patient is
    evaluated, so a typo in a program definition fails fast and loudly.
    """
