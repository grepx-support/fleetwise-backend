from backend.extensions import db
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy import false
from enum import Enum
from backend.models.driver import Driver
from backend.models.vehicle import Vehicle
from backend.models.service import Service
from backend.models.invoice import Invoice
from backend.models.driver_remark import DriverRemark
from backend.models.contractor import Contractor
from backend.models.vehicle_type import VehicleType
import json

class JobStatus(Enum):
    NEW = "new"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    OTW = "otw"
    OTS = "ots"
    POB = "pob"
    JC = "jc"
    SD = "sd"
    CANCELED = "canceled"

class Job(db.Model):
    __tablename__ = 'job'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False, index=True)
    sub_customer_name = db.Column(db.String(128), nullable=True, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='SET NULL'), nullable=True, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id', ondelete='SET NULL'), nullable=True, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id', ondelete='SET NULL'), nullable=True, index=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey('contractor.id', ondelete='SET NULL'), nullable=True, index=True)
    # New: vehicle_type_id references vehicle_type table
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey('vehicle_type.id', ondelete='SET NULL'), nullable=True, index=True)
    service_type = db.Column(db.String(64), nullable=False, index=True)
    pickup_location = db.Column(db.String(256), nullable=False)
    dropoff_location = db.Column(db.String(256), nullable=False)
    pickup_date = db.Column(db.String(32), nullable=False, index=True)
    pickup_time = db.Column(db.String(32), nullable=True)
    passenger_name = db.Column(db.String(128), nullable=True)
    passenger_email = db.Column(db.String(128), nullable=True)
    passenger_mobile = db.Column(db.String(32), nullable=True)
    booking_ref = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), nullable=False, default=JobStatus.NEW.value, index=True)
    extra_services = db.Column(db.Text, nullable=True)
    additional_discount = db.Column(db.Float, nullable=True)
    extra_charges = db.Column(db.Float, nullable=True)
    base_price = db.Column(db.Float, nullable=False)
    final_price = db.Column(db.Float, nullable=False)
    job_cost = db.Column(db.Float, nullable=True)
    cash_to_collect = db.Column(db.Float, nullable=True)  # New field: Cash to collect from passenger
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='SET NULL'), nullable=True, index=True)
    driver_commission = db.Column(db.Float, nullable=True)
    penalty = db.Column(db.Float, nullable=True)
    # Contractor commission should be calculated dynamically based on ContractorServicePricing
    # using contractor_id and service_id rather than stored directly in this field
    # Note: contractor_commission field removed - use job_cost instead
    
    # Dropoff location columns
    dropoff_loc1 = db.Column(db.Text, nullable=True)
    dropoff_loc2 = db.Column(db.Text, nullable=True)
    dropoff_loc3 = db.Column(db.Text, nullable=True)
    dropoff_loc4 = db.Column(db.Text, nullable=True)
    dropoff_loc5 = db.Column(db.Text, nullable=True)
    
    # Dropoff location price columns
    dropoff_loc1_price = db.Column(db.Float, nullable=True, default=0.0)
    dropoff_loc2_price = db.Column(db.Float, nullable=True, default=0.0)
    dropoff_loc3_price = db.Column(db.Float, nullable=True, default=0.0)
    dropoff_loc4_price = db.Column(db.Float, nullable=True, default=0.0)
    dropoff_loc5_price = db.Column(db.Float, nullable=True, default=0.0)
    
    # Pickup location columns
    pickup_loc1 = db.Column(db.Text, nullable=True)
    pickup_loc2 = db.Column(db.Text, nullable=True)
    pickup_loc3 = db.Column(db.Text, nullable=True)
    pickup_loc4 = db.Column(db.Text, nullable=True)
    pickup_loc5 = db.Column(db.Text, nullable=True)
    
    pickup_loc1_price = db.Column(db.Float, nullable=True, default=0.0)
    pickup_loc2_price = db.Column(db.Float, nullable=True, default=0.0)
    pickup_loc3_price = db.Column(db.Float, nullable=True, default=0.0)
    pickup_loc4_price = db.Column(db.Float, nullable=True, default=0.0)
    pickup_loc5_price = db.Column(db.Float, nullable=True, default=0.0)

    
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())


       # New fields for job tracking
    start_time = db.Column(db.DateTime, nullable=True)  # when driver starts the job
    end_time = db.Column(db.DateTime, nullable=True)    # when job is finished
    
    # Customer remark field
    customer_remark = db.Column(db.Text, nullable=True)
    
    # Relationships - Optimized for performance
    # Use 'select' for most relationships to avoid N+1 queries when not needed
    # Use 'joined' only for frequently accessed relationships in list views
    customer = db.relationship('Customer', backref='job_customer', lazy='select')
    driver = db.relationship('Driver', backref='job_driver', lazy='select')
    vehicle = db.relationship('Vehicle', backref='job_vehicle', lazy='select')
    vehicle_type = db.relationship('VehicleType', backref='job_vehicle_type', lazy='select')
    service = db.relationship('Service', backref='job_service', lazy='select')
    invoice = db.relationship('Invoice', backref='job_invoice', lazy='select')
    driver_remarks = db.relationship("DriverRemark", back_populates="job", cascade="all, delete-orphan")
    contractor = db.relationship('Contractor', back_populates='jobs', lazy='select')
    # Use string reference to avoid circular import issues
    midnight_surcharge = db.Column(db.Float, nullable=True, default=0.0)
    
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id', ondelete='SET NULL'), nullable=True, index=True)
    # JSON serialization/deserialization for extra_services
    @property
    def extra_services_data(self):
        """Get extra_services as parsed JSON data"""
        if self.extra_services:
            try:
                return json.loads(self.extra_services)
            except (json.JSONDecodeError, TypeError):
                return []
        return []
    
    @extra_services_data.setter
    def extra_services_data(self, value):
        """Set extra_services as JSON string"""
        self.extra_services = json.dumps(value) if value else None
    
   
    
    @classmethod
    def get_with_relationships(cls, job_id=None, include_relationships=None):
        """
        Get jobs with selective relationship loading for better performance.
        
        Args:
            job_id: Specific job ID to fetch (optional)
            include_relationships: List of relationship names to eagerly load
                                 ('customer', 'driver', 'vehicle', 'service', 'invoice', 'sub_customer')
        
        Returns:
            Job query with optimized relationship loading
        """
        if include_relationships is None:
            include_relationships = ['customer', 'driver', 'vehicle']  # Most commonly accessed
        
        query = cls.query
        
        # Add eager loading for specified relationships
        for rel in include_relationships:
            if hasattr(cls, rel):
                query = query.options(db.joinedload(getattr(cls, rel)))
        
        if job_id:
            return query.get(job_id)
        else:
            return query
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query
    
    __table_args__ = (
        db.CheckConstraint(
            f"status IN ({', '.join([repr(status.value) for status in JobStatus])})",
            name='check_job_status'
        ),
    ) 
    def can_transition_to(self, new_status):
        """
        Determine if the job can legally move from its current status to `new_status`
        according to business rules.
        
        Business Rules:
        - NEW -> PENDING or CONFIRMED
        - PENDING -> CONFIRMED only
        - CONFIRMED -> OTW, OTS, SD, POB, JC
        - OTW -> OTS, SD, POB, JC
        - OTS -> SD, POB, JC
        - POB -> SD, JC
        - JC -> SD
        - SD -> (terminating state)
        - CANCELED -> (terminating state)
        """
        # Terminating states - no further transitions allowed
        if self.status in [JobStatus.SD.value, JobStatus.CANCELED.value]:
            return False
            
        # JC can only transition to SD
        if self.status == JobStatus.JC.value:
            return new_status == JobStatus.SD.value
            
        # POB can transition to SD or JC
        if self.status == JobStatus.POB.value:
            return new_status in [JobStatus.SD.value, JobStatus.JC.value]
            
        # OTS can transition to SD, POB, or JC
        if self.status == JobStatus.OTS.value:
            return new_status in [JobStatus.SD.value, JobStatus.POB.value, JobStatus.JC.value]
            
        # OTW can transition to OTS, SD, POB, or JC
        if self.status == JobStatus.OTW.value:
            return new_status in [JobStatus.OTS.value, JobStatus.SD.value, JobStatus.POB.value, JobStatus.JC.value]
            
        # Confirmed can transition to OTW, OTS, SD, POB, or JC
        if self.status == JobStatus.CONFIRMED.value:
            return new_status in [JobStatus.OTW.value, JobStatus.OTS.value, JobStatus.SD.value, JobStatus.POB.value, JobStatus.JC.value]
            
        # Pending can only transition to Confirmed
        if self.status == JobStatus.PENDING.value:
            return new_status == JobStatus.CONFIRMED.value
            
        # NEW can transition to PENDING or CONFIRMED
        if self.status == JobStatus.NEW.value:
            return new_status in [JobStatus.PENDING.value, JobStatus.CONFIRMED.value]
            
        return False  # Default case - no transition allowed

    @property
    def duration_minutes(self):
        if self.start_time and self.end_time:
            duration_seconds = (self.end_time - self.start_time).total_seconds()
            return max(0, duration_seconds / 60)  # Ensure non-negative
        return None

    @property
    def duration_str(self):
        """Return job duration formatted as 'Xh Ym'."""
        if self.start_time and self.end_time:
            duration_seconds = (self.end_time - self.start_time).total_seconds()
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    @property
    def bill_details(self):
        """Get the associated bill if it exists"""
        if self.bill_id:
            from backend.models.bill import Bill
            return Bill.query.get(self.bill_id)
        return None