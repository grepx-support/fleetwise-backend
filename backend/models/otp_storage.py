from backend.extensions import db
from datetime import datetime, timedelta
import secrets
import string


class OTPStorage(db.Model):
    __tablename__ = 'otp_storage'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(128), nullable=False, index=True)
    otp = db.Column(db.String(6), nullable=False, index=True)  # 6-digit OTP
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    @classmethod
    def generate_otp(cls, email, expiry_minutes=15):
        """
        Generate and store a new OTP for the given email
        
        Args:
            email (str): Email to associate with the OTP
            expiry_minutes (int): Number of minutes until OTP expires (default 10)
            
        Returns:
            str: The generated OTP
        """
        # Remove any existing unused OTPs for this email
        cls.cleanup_unused_otps(email)
        
        # Generate 6-digit numeric OTP
        otp = ''.join(secrets.choice(string.digits) for _ in range(6))
        
        # Calculate expiry time
        expires_at = datetime.utcnow() + timedelta(minutes=expiry_minutes)
        
        # Create new OTP record
        otp_record = cls(
            email=email,
            otp=otp,
            expires_at=expires_at
        )
        
        db.session.add(otp_record)
        db.session.commit()
        
        return otp
    
    @classmethod
    def verify_otp(cls, email, otp):
        """
        Verify if the provided OTP is valid for the given email
        
        Args:
            email (str): Email associated with the OTP
            otp (str): OTP to verify
            
        Returns:
            bool: True if OTP is valid, False otherwise
        """
        otp_record = cls.query.filter_by(email=email, otp=otp, used=False).first()
        
        if not otp_record:
            return False
        
        # Check if OTP has expired
        if datetime.utcnow() > otp_record.expires_at:
            # Mark as used to prevent reuse
            otp_record.used = True
            db.session.commit()
            return False
        
        # For reusability within validity period, don't mark as used immediately
        # Only mark as used after successful password reset or when explicitly required
        
        return True
    
    @classmethod
    def cleanup_unused_otps(cls, email):
        """
        Remove any existing unused OTPs for the given email
        
        Args:
            email (str): Email to clean up OTPs for
        """
        unused_otps = cls.query.filter_by(email=email, used=False).all()
        for otp_record in unused_otps:
            db.session.delete(otp_record)
        db.session.commit()
    
    @classmethod
    def cleanup_expired_otps(cls):
        """
        Remove all expired OTPs from the database
        
        Returns:
            int: Number of expired OTPs removed
        """
        expired_otps = cls.query.filter(
            cls.expires_at < datetime.utcnow(),
            cls.used == False
        ).all()
        
        count = len(expired_otps)
        for otp_record in expired_otps:
            db.session.delete(otp_record)
        
        if count > 0:
            db.session.commit()
        
        return count