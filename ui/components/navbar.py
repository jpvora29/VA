from dash import html, dcc
import dash_bootstrap_components as dbc
import pandas as pd


def build_navbar() -> None:
    return html.Header(
        [
            dbc.Container(
                [
                    html.Div(
                        [
                            # Left: Hamburger + Logo
                            html.Div(
                                [
                                    html.Img(
                                        src="/assets/MarshLogo.png",
                                        className="navbar-logo",
                                    )
                                ],
                                className="navbar-branding",
                            ),
                            # Center: Title
                            html.Div("ICG Virtual Analyst", className="navbar-title"),
                            # Right: Nav Items
                            html.Div(
                                [
                                    dbc.Nav(
                                        [
                                            dbc.NavItem(
                                                dbc.NavLink(
                                                    [
                                                        html.I(
                                                            className="bi bi-robot",
                                                            style={
                                                                "paddingRight": "5px"
                                                            },
                                                        ),
                                                        "Chatbot",
                                                    ],
                                                    href="#",
                                                    id="nav-chatbot",
                                                    active=True,
                                                    className="nav-link-btn",
                                                )
                                            )
                                        ],
                                        className="d-flex gap-4",
                                    )
                                ],
                                className="header-nav",
                            ),
                        ],
                        className="d-flex justify-content-between align-items-center flex-wrap",
                    )
                ],
                fluid=True,
            )
        ],
        className="custom-navbar",
    )
