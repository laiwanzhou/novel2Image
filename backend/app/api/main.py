from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.chapters import router as chapters_router
from app.api.routes.novels import router as novels_router
from app.api.routes.operator import router as operator_router
from app.api.routes.prompts import router as prompts_router
from app.api.routes.review import router as review_router
from app.api.routes.states import router as states_router
from app.api.routes.states import state_router


def create_app() -> FastAPI:
    app = FastAPI(title="Novel Character Visualization")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(review_router)
    app.include_router(states_router)
    app.include_router(state_router)
    app.include_router(prompts_router)
    app.include_router(novels_router)
    app.include_router(chapters_router)
    app.include_router(operator_router)

    return app


app = create_app()
