import pytest
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import secrets
import hashlib

from backend.server import app
from backend.extensions import db, mail
from backend.models.user import User
from backend.models.role import Role
from backend.models.password_reset_token import PasswordResetToken
from backend.services.password_reset_service import PasswordResetService, PasswordResetError
from backend.utils.validation import (
    validate_password_strength,
    validate_password_change_data,
    validate_password_reset_request_data,
    validate_password_reset_data
)
from flask_security.utils import hash_password


class TestPasswordValidation(unittest.TestCase):
    """Test password validation utility functions"""
    
    def test_validate_password_strength_valid_password(self):
        """Test valid password passes all requirements"""
        password = "SecurePass123!"
        is_valid, errors = validate_password_strength(password)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_validate_password_strength_short_password(self):
        """Test password too short fails validation"""
        password = "Short1!"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must be at least 8 characters long', errors)
    
    def test_validate_password_strength_no_uppercase(self):
        """Test password without uppercase fails validation"""
        password = "lowercase123!"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must contain at least one uppercase letter', errors)
    
    def test_validate_password_strength_no_lowercase(self):
        """Test password without lowercase fails validation"""
        password = "UPPERCASE123!"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must contain at least one lowercase letter', errors)
    
    def test_validate_password_strength_no_digit(self):
        """Test password without digit fails validation"""
        password = "SecurePass!"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must contain at least one number', errors)
    
    def test_validate_password_strength_no_special_char(self):
        """Test password without special character fails validation"""
        password = "SecurePass123"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must contain at least one special character', errors)
    
    def test_validate_password_strength_too_long(self):
        """Test password that's too long fails validation"""
        password = "A" * 129 + "1!"
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password must not exceed 128 characters', errors)
    
    def test_validate_password_strength_empty_password(self):
        """Test empty password fails validation"""
        password = ""
        is_valid, errors = validate_password_strength(password)
        self.assertFalse(is_valid)
        self.assertIn('Password is required', errors)
    
    def test_validate_password_change_data_valid(self):
        """Test valid password change data"""
        data = {
            'current_password': 'OldPassword123!',
            'new_password': 'NewPassword123!'
        }
        is_valid, errors = validate_password_change_data(data)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_validate_password_change_data_missing_current(self):
        """Test password change data missing current password"""
        data = {
            'new_password': 'NewPassword123!'
        }
        is_valid, errors = validate_password_change_data(data)
        self.assertFalse(is_valid)
        self.assertIn('current_password', errors)
    
    def test_validate_password_change_data_same_passwords(self):
        """Test password change data with same current and new password"""
        data = {
            'current_password': 'SamePassword123!',
            'new_password': 'SamePassword123!'
        }
        is_valid, errors = validate_password_change_data(data)
        self.assertFalse(is_valid)
        self.assertIn('New password must be different from current password', errors['new_password'])
    
    def test_validate_password_reset_request_data_valid(self):
        """Test valid password reset request data"""
        data = {'email': 'test@example.com'}
        is_valid, errors = validate_password_reset_request_data(data)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_validate_password_reset_request_data_invalid_email(self):
        """Test invalid email format"""
        data = {'email': 'invalid-email'}
        is_valid, errors = validate_password_reset_request_data(data)
        self.assertFalse(is_valid)
        self.assertIn('Invalid email format', errors['email'])
    
    def test_validate_password_reset_data_valid(self):
        """Test valid password reset data"""
        data = {
            'new_password': 'NewPassword123!',
            'confirm_password': 'NewPassword123!'
        }
        is_valid, errors = validate_password_reset_data(data)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_validate_password_reset_data_mismatch(self):
        """Test password reset data with mismatched passwords"""
        data = {
            'new_password': 'NewPassword123!',
            'confirm_password': 'DifferentPassword123!'
        }
        is_valid, errors = validate_password_reset_data(data)
        self.assertFalse(is_valid)
        self.assertIn('Password confirmation does not match new password', errors['confirm_password'])


class TestPasswordResetToken(unittest.TestCase):
    """Test PasswordResetToken model"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
    
    def tearDown(self):
        """Clean up test environment"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
    
    def test_create_token(self):
        """Test token creation"""
        user_id = 1
        token, raw_token = PasswordResetToken.create_token(user_id)
        
        self.assertEqual(token.user_id, user_id)
        self.assertIsNotNone(token.token_hash)
        self.assertIsNotNone(token.expires_at)
        self.assertFalse(token.used)
        self.assertIsNotNone(raw_token)
        self.assertEqual(len(raw_token), 43)  # URL-safe base64 with 32 bytes = 43 chars
    
    def test_verify_token_valid(self):
        """Test verifying a valid token"""
        user_id = 1
        token, raw_token = PasswordResetToken.create_token(user_id)
        db.session.add(token)
        db.session.commit()
        
        verified_token = PasswordResetToken.verify_token(raw_token)
        self.assertIsNotNone(verified_token)
        self.assertEqual(verified_token.user_id, user_id)
    
    def test_verify_token_invalid(self):
        """Test verifying an invalid token"""
        invalid_token = "invalid_token_string"
        verified_token = PasswordResetToken.verify_token(invalid_token)
        self.assertIsNone(verified_token)
    
    def test_verify_token_expired(self):
        """Test verifying an expired token"""
        user_id = 1
        token, raw_token = PasswordResetToken.create_token(user_id)
        # Manually set expiry to past
        token.expires_at = datetime.utcnow() - timedelta(hours=1)
        db.session.add(token)
        db.session.commit()
        
        verified_token = PasswordResetToken.verify_token(raw_token)
        self.assertIsNone(verified_token)
    
    def test_verify_token_used(self):
        """Test verifying a used token"""
        user_id = 1
        token, raw_token = PasswordResetToken.create_token(user_id)
        token.mark_as_used()
        db.session.add(token)
        db.session.commit()
        
        verified_token = PasswordResetToken.verify_token(raw_token)
        self.assertIsNone(verified_token)
    
    def test_mark_as_used(self):
        """Test marking token as used"""
        user_id = 1
        token, _ = PasswordResetToken.create_token(user_id)
        
        self.assertFalse(token.used)
        self.assertIsNone(token.used_at)
        
        token.mark_as_used()
        
        self.assertTrue(token.used)
        self.assertIsNotNone(token.used_at)
    
    def test_is_expired(self):
        """Test token expiry check"""
        user_id = 1
        token, _ = PasswordResetToken.create_token(user_id)
        
        # Fresh token should not be expired
        self.assertFalse(token.is_expired())
        
        # Manually expire token
        token.expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.assertTrue(token.is_expired())
    
    def test_cleanup_expired_tokens(self):
        """Test cleanup of expired tokens"""
        user_id = 1
        
        # Create expired token
        expired_token, _ = PasswordResetToken.create_token(user_id)
        expired_token.expires_at = datetime.utcnow() - timedelta(hours=1)
        
        # Create used token
        used_token, _ = PasswordResetToken.create_token(user_id)
        used_token.mark_as_used()
        
        # Create valid token
        valid_token, _ = PasswordResetToken.create_token(user_id)
        
        db.session.add_all([expired_token, used_token, valid_token])
        db.session.commit()
        
        # Should have 3 tokens before cleanup
        self.assertEqual(PasswordResetToken.query.count(), 3)
        
        # Cleanup should remove 2 tokens (expired and used)
        cleaned_count = PasswordResetToken.cleanup_expired_tokens()
        self.assertEqual(cleaned_count, 2)
        
        # Should have 1 token remaining
        self.assertEqual(PasswordResetToken.query.count(), 1)
        remaining_token = PasswordResetToken.query.first()
        self.assertEqual(remaining_token.id, valid_token.id)


if __name__ == '__main__':
    unittest.main()