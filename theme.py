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

        /* ── Global font & text colour ── */
        html, body, .stApp,
        h1, h2, h3, h4, h5, h6,
        p, span, label, div,
        [data-testid="stSidebar"] *,
        .stMarkdown, .stMarkdown p, .stMarkdown li,
        .stText, .stCaption {
            font-family: Georgia, 'Times New Roman', serif !important;
            color: #1A1A1A !important;
        }

        /* ── Headings ── */
        h1, h2, h3 {
            color: #1A1A1A !important;
        }

        /* ── Selectbox & multiselect display text ── */
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
        input, textarea, [data-baseweb="input"] {
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
