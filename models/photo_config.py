from backend.extensions import db

class PhotoConfig(db.Model):
    __tablename__ = "photo_config"

    id = db.Column(db.Integer, primary_key=True)
    stage = db.Column(db.String(50), nullable=False, unique=True)   # pickup, dropoff, incident, etc.
    max_photos = db.Column(db.Integer, default=3)                   # configurable, default 3
    max_size_mb = db.Column(db.Float, default=2.0)                  # max size after compression
    allowed_formats = db.Column(db.String(100), default="jpg,png")  # supported formats

    def __repr__(self):
        return f"<PhotoConfig {self.stage} max={self.max_photos}>"
    