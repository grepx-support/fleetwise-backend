import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.extensions import db


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_token'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    salt = db.Column(db.String(128), nullable=True)  # Make salt nullable to handle existing records
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    
    # Relationship to user
    user = db.relationship('User', backref='password_reset_tokens')
    
    def __init__(self, user_id, expiry_hours=1):
        """
        Create a new password reset token
        
        Args:
            user_id: The ID of the user requesting password reset
            expiry_hours: Hours until token expires (default: 1 hour)
        """
        self.user_id = user_id
        self.expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
        # Generate a secure random token
        self.raw_token = secrets.token_urlsafe(32)
        
        # Generate a random salt for secure hashing
        salt = os.urandom(32)
        # Use PBKDF2 with salt for secure token hashing
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        self.token_hash = base64.b64encode(kdf.derive(self.raw_token.encode())).decode()
        self.salt = base64.b64encode(salt).decode()
    
    @classmethod
    def create_token(cls, user_id, expiry_hours=1):
        """
        Create and return a new password reset token instance
        
        Args:
            user_id: The ID of the user requesting password reset
            expiry_hours: Hours until token expires (default: 1 hour)
            
        Returns:
            tuple: (PasswordResetToken instance, raw_token_string)
        """
        token = cls(user_id, expiry_hours)
        return token, token.raw_token
    
    @classmethod
    def _hash_token_with_salt(cls, raw_token, salt):
        """
        Hash a token with the provided salt using PBKDF2
        
        Args:
            raw_token: The raw token string to hash
            salt: The base64 encoded salt
            
        Returns:
            str: The base64 encoded hashed token
        """
        salt_bytes = base64.b64decode(salt.encode())
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt_bytes,
            iterations=100000,
        )
        return base64.b64encode(kdf.derive(raw_token.encode())).decode()
    
    @classmethod
    def _hash_token_without_salt(cls, raw_token):
        """
        Hash a token without salt using SHA-256 (for backward compatibility with existing tokens)
        
        Args:
            raw_token: The raw token string to hash
            
        Returns:
            str: The hex digest of the hashed token
        """
        return hashlib.sha256(raw_token.encode()).hexdigest()
    
    @classmethod
    def verify_token(cls, raw_token):
        """
        Verify a password reset token using salted hashing (new) or unsalted hashing (existing tokens)
        
        Args:
            raw_token: The raw token string to verify
            
        Returns:
            PasswordResetToken: The token instance if valid, None otherwise
        """
        if not raw_token:
            return None
            
        # First try to find tokens with salt (new method)
        if raw_token:
            tokens_with_salt = cls.query.filter_by(used=False).filter(cls.salt.isnot(None)).all()
            
            for token in tokens_with_salt:
                # Hash the provided token with the stored salt
                token_hash = cls._hash_token_with_salt(raw_token, token.salt)
                
                # Check if hashes match and token is still valid
                if (token_hash == token.token_hash and 
                    not token.is_expired() and 
                    not token.used):
                    return token
        
        # For backward compatibility, also check tokens without salt (old method)
        # This is for existing tokens created before the salt was added
        token_hash_unsalted = cls._hash_token_without_salt(raw_token)
        token = cls.query.filter_by(token_hash=token_hash_unsalted, used=False).first()
        
        if token and not token.is_expired():
            return token
            
        return None
    
    @classmethod
    def verify_and_consume_token(cls, raw_token):
        """
        Atomically verify and consume token to prevent race conditions using salted hashing (new) or unsalted hashing (existing tokens)
        
        Args:
            raw_token: The raw token string to verify and consume
            
        Returns:
            PasswordResetToken: The token instance if valid and consumed, None otherwise
        """
        if not raw_token:
            return None

        # First try to find and consume tokens with salt (new method)
        tokens_with_salt = cls.query.filter_by(used=False).filter(cls.salt.isnot(None)).all()
        
        for token in tokens_with_salt:
            # Hash the provided token with the stored salt
            token_hash = cls._hash_token_with_salt(raw_token, token.salt)
            
            # Check if hashes match
            if token_hash == token.token_hash:
                # Atomic update with WHERE conditions prevents concurrent usage
                rows_updated = db.session.query(cls).filter(
                    cls.id == token.id,
                    cls.token_hash == token_hash,
                    cls.expires_at > datetime.utcnow(),
                    cls.used == False
                ).update({
                    'used': True,
                    'used_at': datetime.utcnow()
                })
                
                db.session.flush()  # Ensure the update is executed
                
                if rows_updated == 1:
                    return db.session.query(cls).filter_by(id=token.id).first()
        
        # For backward compatibility, also check tokens without salt (old method)
        # This is for existing tokens created before the salt was added
        token_hash_unsalted = cls._hash_token_without_salt(raw_token)
        existing_token = cls.query.filter_by(token_hash=token_hash_unsalted, used=False).first()
        
        if existing_token and not existing_token.is_expired():
            # Atomic update with WHERE conditions prevents concurrent usage
            rows_updated = db.session.query(cls).filter(
                cls.id == existing_token.id,
                cls.token_hash == token_hash_unsalted,
                cls.expires_at > datetime.utcnow(),
                cls.used == False
            ).update({
                'used': True,
                'used_at': datetime.utcnow()
            })
            
            db.session.flush()  # Ensure the update is executed
            
            if rows_updated == 1:
                return db.session.query(cls).filter_by(id=existing_token.id).first()
                    
        return None
    
    def is_expired(self):
        """Check if the token has expired"""
        return datetime.utcnow() > self.expires_at
    
    def mark_as_used(self):
        """Mark the token as used"""
        self.used = True
        self.used_at = datetime.utcnow()
    
    @classmethod
    def cleanup_expired_tokens(cls):
        """Remove expired tokens from database"""
        expired_tokens = cls.query.filter(
            db.or_(
                cls.expires_at < datetime.utcnow(),
                cls.used == True
            )
        ).all()
        
        for token in expired_tokens:
            db.session.delete(token)
        
        return len(expired_tokens)
    
    def __repr__(self):
        return f'<PasswordResetToken user_id={self.user_id} expires_at={self.expires_at} used={self.used}>'