"""FastAPI app: JSON API plus the static survey dashboard."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .collectors import SignalReadError
from .config import Settings, resolve_app_dir
from .floorplan import FloorPlan
from .render import render_svg
from .service import Session, SessionBusy
from .survey import SurveyError

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


class MeasureRequest(BaseModel):
    x: float = Field(..., ge=0, le=500)
    y: float = Field(..., ge=0, le=500)


class AutoSurveyRequest(BaseModel):
    count: int = Field(10, ge=1, le=60)


def create_app(settings: Settings, plan: FloorPlan, mode: Optional[str] = None,
               session: Optional[Session] = None) -> FastAPI:
    session = session or Session(settings, plan, mode or settings.server.mode)
    app_dir = resolve_app_dir()
    app = FastAPI(title="SignalWalk", version=__version__,
                  description="Measure Wi-Fi signal by walking around; map it and find dead zones.")
    app.state.session = session

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    if app_dir is not None:
        app.mount("/static", StaticFiles(directory=app_dir / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        if app_dir is None:
            return JSONResponse({"detail": "Dashboard files not found. Run from the repository root "
                                 "or set SIGNALWALK_APP_DIR."}, status_code=404)
        return FileResponse(app_dir / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "mode": session.mode}

    @app.get("/api/state")
    def state():
        return {"mode": session.mode, "version": __version__, "floorplan": plan.to_dict(),
                "measurements": [m.to_dict() for m in session.survey.measurements],
                "reader": session.reader.name if session.reader else None,
                "readings_per_spot": settings.survey.readings_per_spot,
                "thresholds": {"strong_dbm": settings.thresholds.strong_dbm,
                               "weak_dbm": settings.thresholds.weak_dbm,
                               "dead_dbm": settings.thresholds.dead_dbm}}

    @app.get("/api/analysis")
    def analysis():
        return session.analysis()

    @app.post("/api/measure")
    def measure(body: MeasureRequest):
        try:
            index, m = session.measure(body.x, body.y)
        except SurveyError as exc:
            raise HTTPException(422, str(exc))
        except SessionBusy as exc:
            raise HTTPException(409, str(exc))
        except SignalReadError as exc:
            raise HTTPException(503, f"Could not read Wi-Fi signal: {exc}")
        return {"index": index, "measurement": m.to_dict()}

    @app.delete("/api/measurements/{index}")
    def delete_measurement(index: int):
        try:
            session.remove(index)
        except SurveyError as exc:
            raise HTTPException(404, str(exc))
        return {"removed": index, "count": len(session.survey)}

    @app.post("/api/reset")
    def reset():
        session.reset()
        return {"count": 0}

    @app.post("/api/sim/auto-survey")
    def auto_survey(body: AutoSurveyRequest):
        try:
            batch = session.auto_survey(body.count)
        except SurveyError as exc:
            raise HTTPException(409, str(exc))
        return {"added": len(batch), "count": len(session.survey)}

    @app.get("/api/export/survey.csv")
    def export_csv():
        return Response(session.survey.to_csv(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="survey.csv"'})

    @app.get("/api/export/survey.json")
    def export_json():
        return JSONResponse(session.survey.to_dict(),
                            headers={"Content-Disposition": 'attachment; filename="survey.json"'})

    @app.get("/api/export/heatmap.svg")
    def export_svg():
        svg = render_svg(plan, session.analysis(), session.survey.measurements)
        return Response(svg, media_type="image/svg+xml",
                        headers={"Content-Disposition": 'attachment; filename="heatmap.svg"'})

    return app
