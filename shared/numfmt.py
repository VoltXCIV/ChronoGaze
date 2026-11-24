"""Indonesian number format: '.' groups thousands, ',' marks decimals (1.000,5)."""
from __future__ import annotations

import pandas as pd

_SWAP = str.maketrans({",": ".", ".": ","})


def idn(x, fmt: str = "{:,.2f}") -> str:
    """Format `x` with a Python format string written the usual way
    ("{:,.2f}", "{:+.1f}%", ...) and return it in Indonesian style."""
    return fmt.format(x).translate(_SWAP)


def idn_styler(df: pd.DataFrame, formats: dict[str, str]):
    """A Styler that shows the given columns in Indonesian style but keeps
    the numbers underneath, so sorting in st.dataframe stays numeric.
    Missing values read "—"."""
    return df.style.format({c: (lambda f: lambda v: "—" if pd.isna(v) else idn(v, f))(f)
                            for c, f in formats.items() if c in df.columns})
