"""Injects a modern animated background + glassmorphism styling into the Streamlit app.

Everything here is pure CSS (Streamlit strips <script> from st.markdown, so JS-based particle
effects won't run). The animation is GPU-composited (background-position / transform only) to
keep it cheap. Layers, back to front:
  1. .stApp            -> solid dark base color
  2. .stApp::before    -> drifting "aurora" color blobs
  3. .stApp::after     -> slowly moving grid lines
  4. app content       -> lifted above the animated layers via z-index
"""

import streamlit as st

_CSS = """
<style>
:root {
    --bg-base: #0a0e1a;
    --accent-cyan: 0, 229, 255;
    --accent-purple: 168, 85, 247;
    --accent-pink: 236, 72, 153;
}

/* --- base + animated layers ------------------------------------------------ */
.stApp {
    background: var(--bg-base);
}

/* drifting aurora color blobs */
.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background:
        radial-gradient(circle at 15% 20%, rgba(var(--accent-cyan), 0.16), transparent 38%),
        radial-gradient(circle at 85% 25%, rgba(var(--accent-purple), 0.16), transparent 38%),
        radial-gradient(circle at 50% 85%, rgba(var(--accent-pink), 0.13), transparent 42%);
    background-size: 200% 200%;
    animation: aurora 20s ease-in-out infinite;
}

/* slowly moving grid lines */
.stApp::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background-image:
        linear-gradient(rgba(99, 102, 241, 0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(99, 102, 241, 0.06) 1px, transparent 1px);
    background-size: 46px 46px;
    animation: gridDrift 26s linear infinite;
}

@keyframes aurora {
    0%,  100% { background-position:   0%   0%, 100%   0%, 50% 100%; }
    50%       { background-position: 100% 100%,   0% 100%, 50%   0%; }
}

@keyframes gridDrift {
    from { background-position: 0 0, 0 0; }
    to   { background-position: 46px 46px, 46px 46px; }
}

/* lift real content above the animated background layers */
[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppViewContainer"] .block-container {
    position: relative;
    z-index: 1;
}

/* --- glassmorphism sidebar ------------------------------------------------- */
[data-testid="stSidebar"] {
    background: rgba(17, 24, 39, 0.55);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
}

/* --- gradient title -------------------------------------------------------- */
[data-testid="stAppViewContainer"] h1 {
    background: linear-gradient(90deg,
        rgb(var(--accent-cyan)), rgb(var(--accent-purple)), rgb(var(--accent-pink)));
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    background-size: 200% auto;
    animation: shimmer 6s linear infinite;
}

@keyframes shimmer {
    to { background-position: 200% center; }
}

/* --- buttons: subtle glass + glow on hover --------------------------------- */
.stButton > button {
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.04);
    transition: all 0.2s ease;
}
.stButton > button:hover {
    border-color: rgba(var(--accent-cyan), 0.6);
    box-shadow: 0 0 16px rgba(var(--accent-cyan), 0.35);
    transform: translateY(-1px);
}

/* --- query editor + dataframe: faint glass panels -------------------------- */
.stTextArea textarea,
[data-testid="stDataFrame"] {
    background: rgba(255, 255, 255, 0.03) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px;
}
</style>
"""


def inject_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
