"""Azure Functions entry point (Python v2 programming model).

Week 1 only exposes a health probe. Ingestion (backfill, Graph change notifications),
enrichment and the search API are added in weeks 2-4 as blueprints.
"""

import json

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json")
