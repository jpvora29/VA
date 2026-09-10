"""Browser selection and event acceptance, separate from graph execution."""
from dash import ALL, ClientsideFunction, Input, Output, State, clientside_callback


clientside_callback(
    "function(cursor) { return !!(cursor || {}).loading; }",
    Output("send-btn", "disabled"), Input("chat-cursor", "data"),
)


clientside_callback(
    ClientsideFunction(namespace="chatLifecycle", function_name="select"),
    Output("chat-cursor", "data"),
    Output("chat-loading", "hidden"),
    Output("job-poll", "disabled", allow_duplicate=True),
    Output("is-thinking", "data", allow_duplicate=True),
    Output("active-conversation", "data", allow_duplicate=True),
    Input("chat-store", "data"),
    Input({"type": "conv-item", "id": ALL}, "n_clicks"),
    Input("new-chat-btn", "n_clicks"),
    State("active-conversation", "data"),
    State("chat-cursor", "data"),
    prevent_initial_call="initial_duplicate",
)

clientside_callback(
    ClientsideFunction(namespace="chatLifecycle", function_name="publishJob"),
    Output("chat-job-ack", "data"),
    Input("job-event", "data"), State("chat-cursor", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="chatLifecycle", function_name="publishLoad"),
    Output("chat-load-ack", "data"),
    Input("conversation-load", "data"), State("chat-cursor", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="chatLifecycle", function_name="acceptRender"),
    Output("chat-box", "children", allow_duplicate=True),
    Output("live-draft", "children", allow_duplicate=True),
    Input("chat-render", "data"), State("chat-cursor", "data"),
    prevent_initial_call=True,
)
