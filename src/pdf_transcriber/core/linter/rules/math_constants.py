"""Shared math constants, data mappings, and helpers for linter rules.

This module centralizes:
- UNICODE_TO_LATEX: Unicode → LaTeX symbol mapping
- MATH_PATTERNS: Common unwrapped math expression patterns
- is_in_math_mode(): Helper to detect if a position is inside $...$ delimiters

Used by both math.py and html.py rule modules.
"""
import re


# Unicode to LaTeX mapping for common math symbols
UNICODE_TO_LATEX = {
    # Greek letters (commonly appear outside $...$)
    '◦': r'\circ',
    '∗': '*',
    '∞': r'\infty',
    'Ω': r'\Omega',
    'α': r'\alpha',
    'β': r'\beta',
    'γ': r'\gamma',
    'δ': r'\delta',
    'ε': r'\varepsilon',
    'ζ': r'\zeta',
    'η': r'\eta',
    'θ': r'\theta',
    'ι': r'\iota',
    'κ': r'\kappa',
    'λ': r'\lambda',
    'μ': r'\mu',
    'ν': r'\nu',
    'ξ': r'\xi',
    'π': r'\pi',
    'ρ': r'\rho',
    'σ': r'\sigma',
    'τ': r'\tau',
    'υ': r'\upsilon',
    'φ': r'\varphi',
    'χ': r'\chi',
    'ψ': r'\psi',
    'ω': r'\omega',
    'Γ': r'\Gamma',
    'Δ': r'\Delta',
    'Θ': r'\Theta',
    'Λ': r'\Lambda',
    'Ξ': r'\Xi',
    'Π': r'\Pi',
    'Σ': r'\Sigma',
    'Υ': r'\Upsilon',
    'Φ': r'\Phi',
    'Ψ': r'\Psi',

    # Relations
    '∈': r'\in',
    '∉': r'\notin',
    '⊂': r'\subset',
    '⊃': r'\supset',
    '⊆': r'\subseteq',
    '⊇': r'\supseteq',
    '≤': r'\leq',
    '≥': r'\geq',
    '≠': r'\neq',
    '≈': r'\approx',
    '≡': r'\equiv',
    '∼': r'\sim',
    '≃': r'\simeq',
    '≅': r'\cong',
    '∝': r'\propto',

    # Arrows
    '→': r'\to',
    '←': r'\leftarrow',
    '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow',
    '⇐': r'\Leftarrow',
    '⇔': r'\Leftrightarrow',
    '↦': r'\mapsto',
    '↪': r'\hookrightarrow',
    '↠': r'\twoheadrightarrow',

    # Operators
    '×': r'\times',
    '÷': r'\div',
    '±': r'\pm',
    '∓': r'\mp',
    '⊗': r'\otimes',
    '⊕': r'\oplus',
    '∩': r'\cap',
    '∪': r'\cup',
    '∧': r'\wedge',
    '∨': r'\vee',
    '∘': r'\circ',
    '·': r'\cdot',
    '†': r'\dagger',
    '‡': r'\ddagger',

    # Quantifiers and logic
    '∀': r'\forall',
    '∃': r'\exists',
    '∄': r'\nexists',
    '¬': r'\neg',
    '∅': r'\emptyset',

    # Calculus and analysis
    '∂': r'\partial',
    '∇': r'\nabla',
    '∫': r'\int',
    '∑': r'\sum',
    '∏': r'\prod',
    '√': r'\sqrt',

    # Misc
    '⊥': r'\perp',
    '∥': r'\parallel',
    '⟨': r'\langle',
    '⟩': r'\rangle',
    '⌊': r'\lfloor',
    '⌋': r'\rfloor',
    '⌈': r'\lceil',
    '⌉': r'\rceil',
    '♭': r'\flat',
    '♯': r'\sharp',
    '♮': r'\natural',
    'ℓ': r'\ell',
    'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}',
    'ℚ': r'\mathbb{Q}',
    'ℝ': r'\mathbb{R}',
    'ℂ': r'\mathbb{C}',
}

# Patterns that indicate unwrapped math when outside $...$
MATH_PATTERNS = [
    # Letter with Unicode superscript/subscript
    (r'([A-Za-z])◦◦', r'$\1^{\circ\circ}$'),  # K◦◦ → $K^{\circ\circ}$
    (r'([A-Za-z])◦(?!◦)', r'$\1^{\circ}$'),   # K◦ → $K^{\circ}$ (not K◦◦)
    (r'([A-Za-z])∗', r'$\1^*$'),               # K∗ → $K^*$

    # Common perfectoid/p-adic patterns
    (r'\|([A-Za-z])\|', r'$|\1|$'),            # |K| → $|K|$
    (r'\|([A-Za-z])\∗\|', r'$|\1^*|$'),        # |K∗| → $|K^*|$
]


def is_in_math_mode(content: str, pos: int) -> bool:
    """Check if position is inside $...$ math mode.

    Looks backwards from the given position and counts unescaped dollar signs.
    An odd count means we're inside an inline math environment.
    """
    before = content[max(0, pos - 200):pos]
    dollars = len(re.findall(r'(?<!\\)\$', before))
    return dollars % 2 == 1
