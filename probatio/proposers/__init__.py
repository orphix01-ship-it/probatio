"""Proposer registry."""
from .classical import ExhaustiveProposer, MutationProposer, RandomProposer
from .llm import LLMProposer, ProgramEvolutionProposer

PROPOSERS = {p.name: p for p in (RandomProposer, MutationProposer, ExhaustiveProposer,
                                 LLMProposer, ProgramEvolutionProposer)}
