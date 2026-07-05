"""개발 서버 실행 진입점.

    python run.py                 # http://127.0.0.1:5000
    PORT=8000 python run.py

운영 배포 시에는 gunicorn 등 WSGI 서버 사용을 권장:
    gunicorn -w 2 -b 0.0.0.0:8000 "webapp:create_app()"
"""
import os

from webapp import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )
