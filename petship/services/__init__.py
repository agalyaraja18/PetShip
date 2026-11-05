"""Service layer: business logic and thin wrappers around external providers.

Provider wrappers (email, storage, AI) are fallback-first: they operate
without paid keys so the app runs end-to-end in development.
"""
