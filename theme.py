import streamlit as st


def apply_newspaper_theme():
    # Explicitly load the Material Symbols Outlined font file so the icon
    # glyph is available regardless of what Streamlit's own <head> emits.
    st.markdown(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
        /* ── Page & sidebar backgrounds ── */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        .main .block-container {
            background-color: #F4F1E8 !important;
        }
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div,
        section[data-testid="stSidebar"] {
            background-color: #F4F1E8 !important;
        }

        /* ── Global font & text colour (text-bearing elements only) ── */
        h1, h2, h3, h4, h5, h6,
        p, label,
        .stMarkdown, .stMarkdown p, .stMarkdown li,
        .stText, .stCaption,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* Broad div/span serif — exclude icon class names */
        div:not([class*="material"]):not([class*="Material"]),
        span:not([class*="material"]):not([class*="Material"]):not(.material-symbols-rounded):not(.material-symbols-outlined):not(.material-icons) {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* ── Material Symbols icon font restore ──
           Each rule is its own block so specificity matches the broad rule above.
           The font-file is guaranteed loaded by the <link> injected above. ── */
        .material-symbols-outlined {
            font-family: 'Material Symbols Outlined' !important;
        }
        .material-symbols-rounded {
            font-family: 'Material Symbols Rounded' !important;
        }
        .material-symbols-sharp {
            font-family: 'Material Symbols Sharp' !important;
        }
        .material-icons {
            font-family: 'Material Icons' !important;
        }

        /* ── Headings colour ── */
        h1, h2, h3 {
            color: #1A1A1A !important;
        }

        /* ── Selectbox / multiselect outer border ── */
        [data-baseweb="select"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }
        [data-baseweb="input"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }

        /* ── Tag parent containers — fix clipping ──
           BaseWeb renders tags inside nested divs under [data-baseweb="select"].
           Those inner divs can have overflow:hidden / a fixed height that clips
           children when a wider serif font is used.  Force them all to be
           auto-sized and visible so tag text is never cut off. ── */
        [data-baseweb="select"] > div,
        [data-baseweb="select"] > div > div {
            border: none !important;
            overflow: visible !important;
            height: auto !important;
            min-height: 36px;
            flex-wrap: wrap !important;
        }

        /* ── Multiselect tag / pill ── */
        [data-baseweb="tag"] {
            width: auto !important;
            max-width: none !important;
            min-width: fit-content !important;
            overflow: visible !important;
            white-space: nowrap !important;
            padding-left: 10px !important;
            padding-right: 8px !important;
        }
        [data-baseweb="tag"] span,
        [data-baseweb="tag"] [data-testid="stMarkdownContainer"] {
            overflow: visible !important;
            text-overflow: unset !important;
            white-space: nowrap !important;
        }

        /* ── Selectbox display text ── */
        [data-baseweb="select"] span,
        [data-baseweb="select"] div,
        [data-baseweb="tag"] span {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* ── Dataframe / table cells ── */
        .stDataFrame td, .stDataFrame th,
        [data-testid="stDataFrame"] td,
        [data-testid="stDataFrame"] th,
        .dataframe td, .dataframe th {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
            background-color: #F4F1E8 !important;
        }

        /* ── Input widgets text ── */
        input, textarea {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
            background-color: #F4F1E8 !important;
        }

        /* ── Button text (red backgrounds kept intact) ── */
        .stButton > button {
            font-family: Georgia, 'Times New Roman', serif !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
