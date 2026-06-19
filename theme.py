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
        /* 0. Reduce default top padding above page headings */
        .main .block-container,
        [data-testid="stMain"] .block-container {
            padding-top: 1rem !important;
        }

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

        thead th, [data-testid="stDataFrameResizable"] th, [data-testid="stTable"] th, .stDataFrame th, table th {
          color: #FFFFFF !important;
        }

        /* ── Sidebar account / logout button ──
           Scan buttons use type="primary" so they are unaffected by this rule.
           The `p` sub-rule is required because Streamlit renders button text
           inside a <p>, which the broad `p { color: #1A1A1A }` rule would
           otherwise override. */
        [data-testid="stSidebar"] button[kind="secondary"],
        [data-testid="stSidebar"] [data-testid="baseButton-secondary"] {
            width: 100% !important;
            font-size: 14px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
            background: #1A1A1A !important;
            color: #F4F1E8 !important;
            border: 1px solid #1A1A1A !important;
            padding: 10px !important;
            border-radius: 0 !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"] p,
        [data-testid="stSidebar"] button[kind="secondary"] span,
        [data-testid="stSidebar"] [data-testid="baseButton-secondary"] p,
        [data-testid="stSidebar"] [data-testid="baseButton-secondary"] span {
            color: #F4F1E8 !important;
        }

        /* ── Sidebar page navigation ── */
        [data-testid="stSidebarNav"] {
            border-top: 1px solid #1A1A1A !important;
            border-bottom: 1px solid #1A1A1A !important;
            padding: 6px 0 !important;
        }

        /* All nav link spans: uppercase, spaced, 15px */
        [data-testid="stSidebarNavLink"] span {
            font-size: 15px !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
        }

        /* Active page */
        [data-testid="stSidebarNavLink"][aria-current="page"] span {
            font-weight: 700 !important;
            color: #1A1A1A !important;
        }

        /* Inactive pages */
        [data-testid="stSidebarNavLink"]:not([aria-current="page"]) span {
            font-weight: 400 !important;
            color: #6B6B63 !important;
        }

        /* ── Rename nav labels (display only) ──
           Hide the original span text with font-size:0 so the element still
           carries active/inactive color and weight, which ::before inherits. */
        [data-testid="stSidebarNavLink"][href="/"] span,
        [data-testid="stSidebarNavLink"][href="/app"] span {
            font-size: 0 !important;
        }
        [data-testid="stSidebarNavLink"][href="/"] span::before,
        [data-testid="stSidebarNavLink"][href="/app"] span::before {
            content: "NEWS DESK";
            font-size: 15px;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        [data-testid="stSidebarNavLink"][href="/YouTube"] span,
        [data-testid="stSidebarNavLink"][href="/YouTube/"] span {
            font-size: 0 !important;
        }
        [data-testid="stSidebarNavLink"][href="/YouTube"] span::before,
        [data-testid="stSidebarNavLink"][href="/YouTube/"] span::before {
            content: "YOUTUBE MONITOR";
            font-size: 15px;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
