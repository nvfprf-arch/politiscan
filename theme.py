import streamlit as st


def apply_newspaper_theme():
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

        /* ── Global font & text colour ──
           Bug 1 fix: scope to text-bearing elements only; exclude Material Symbols/Icons
           so the sidebar collapse arrow glyph keeps its icon font and renders correctly. ── */
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

        /* Broad div/span font — exclude icon elements */
        div:not([class*="material"]):not([class*="Material"]),
        span:not([class*="material"]):not([class*="Material"]):not(.material-symbols-rounded):not(.material-symbols-outlined):not(.material-icons) {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* Explicitly restore Material Symbols / Material Icons to their own font */
        .material-symbols-rounded,
        .material-symbols-outlined,
        .material-symbols-sharp,
        .material-icons,
        [class*="material-symbols"],
        [class*="material-icons"] {
            font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                         'Material Icons', sans-serif !important;
            color: inherit;
        }

        /* ── Headings ── */
        h1, h2, h3 {
            color: #1A1A1A !important;
        }

        /* ── Selectbox & multiselect display text ──
           Bug 2 fix: add 1px border to the outer container boxes so they appear
           as enclosed fields on the cream background. ── */
        [data-baseweb="select"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }
        [data-baseweb="input"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }
        /* Remove inner border duplication that baseweb adds */
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {
            border: none !important;
        }

        [data-baseweb="select"] span,
        [data-baseweb="select"] div,
        [data-baseweb="tag"] span {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* ── Multiselect tags / pills ──
           Bug 3 fix: prevent text clipping inside red "All Outlets" / "All Channels"
           tags. The wider serif font needs auto width, sufficient padding on both
           sides, nowrap, and visible overflow so no characters are cut off. ── */
        [data-baseweb="tag"] {
            width: auto !important;
            max-width: none !important;
            min-width: 0 !important;
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
            padding-left: 2px !important;
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

        /* ── Button text (keep red backgrounds intact) ── */
        .stButton > button {
            font-family: Georgia, 'Times New Roman', serif !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
