import streamlit as st


def apply_newspaper_theme():
    # Ensure the Material Symbols font file is loaded so icon glyphs render.
    st.markdown(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
        /* 1. Cream background — main area and sidebar */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        .main .block-container,
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div,
        section[data-testid="stSidebar"] {
            background-color: #F4F1E8 !important;
        }

        /* 2. Text color — applied to real text-bearing tags only.
              th is intentionally excluded so table headers with dark
              backgrounds keep their own explicit color (e.g. white). */
        h1, h2, h3, h4, h5, h6,
        p, label, li, td,
        input, textarea {
            color: #1A1A1A !important;
        }

        /* 3. Serif font — scoped narrowly to text tags only.
              Icon elements (span.material-symbols-*, svg, etc.) are NOT in this
              list and are therefore never touched. */
        h1, h2, h3, h4, h5, h6,
        p, label,
        .stMarkdown p,
        .stMarkdown li,
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            font-family: Georgia, 'Times New Roman', serif !important;
        }

        /* 4. Borders on selectbox / multiselect / text-input containers */
        [data-baseweb="select"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }
        [data-baseweb="input"] {
            border: 1px solid #1A1A1A !important;
            border-radius: 0 !important;
        }
        /* Remove the inner border that baseweb renders inside the outer one */
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
