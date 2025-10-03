
import streamlit as st
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, select, func, or_
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import os

st.set_page_config(page_title="WMS Streamlit", page_icon="📦", layout="wide")

DB_URL = "sqlite:///wms_streamlit.db"
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()

# ---------- Models ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="picker")
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    sku = Column(String(64), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    barcode = Column(String(128), unique=True, nullable=True)
    bin_location = Column(String(64), nullable=True)
    reorder_point = Column(Integer, default=0)
    on_hand = Column(Integer, default=0)

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True)
    ref = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    vendor = Column(String(128), nullable=True)
    status = Column(String(16), default="open")  # open, received
    lines = relationship("ReceiptLine", back_populates="receipt", cascade="all, delete-orphan")

class ReceiptLine(Base):
    __tablename__ = "receipt_lines"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    received_qty = Column(Integer, default=0)
    item = relationship("Item")
    receipt = relationship("Receipt", back_populates="lines")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    ref = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    customer = Column(String(128), nullable=True)
    status = Column(String(16), default="open")  # open, picking, packed, shipped, closed
    picked_at = Column(DateTime, nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="order", cascade="all, delete-orphan")

class OrderLine(Base):
    __tablename__ = "order_lines"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    picked_qty = Column(Integer, default=0)
    item = relationship("Item")
    order = relationship("Order", back_populates="lines")

class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    carrier = Column(String(64), nullable=True)
    tracking_no = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    order = relationship("Order", back_populates="shipments")

def seed(session):
    # Items / Receipts / Orders
    if not session.scalar(select(func.count(Item.id))):
        items = [
            Item(sku="SKU-001", name="Cardboard Box Small", barcode="1000001", bin_location="A1-01", reorder_point=20, on_hand=100),
            Item(sku="SKU-002", name="Bubble Wrap 50m", barcode="1000002", bin_location="A1-02", reorder_point=10, on_hand=25),
            Item(sku="SKU-003", name="Packing Tape", barcode="1000003", bin_location="B1-01", reorder_point=15, on_hand=60),
        ]
        session.add_all(items)
        r = Receipt(ref="RCPT-001", vendor="Acme Supplies")
        session.add(r); session.flush()
        session.add_all([
            ReceiptLine(receipt_id=r.id, item_id=1, qty=50),
            ReceiptLine(receipt_id=r.id, item_id=2, qty=10),
        ])
        o = Order(ref="ORD-001", customer="PT Nusantara")
        session.add(o); session.flush()
        session.add_all([
            OrderLine(order_id=o.id, item_id=1, qty=5),
            OrderLine(order_id=o.id, item_id=3, qty=2),
        ])
        session.commit()

    # Demo users
    if not session.scalar(select(func.count(User.id))):
        admin = User(username="admin", role="admin"); admin.set_password("admin123")
        sup = User(username="supervisor", role="supervisor"); sup.set_password("super123")
        pick = User(username="picker", role="picker"); pick.set_password("picker123")
        session.add_all([admin, sup, pick]); session.commit()

def ensure_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        seed(s)

ensure_db()

# ---------- Auth helpers ----------
def login_form():
    st.subheader("Login")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", placeholder="admin / supervisor / picker")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        with SessionLocal() as s:
            user = s.execute(select(User).where(User.username==username)).scalar_one_or_none()
            if user and user.check_password(password):
                st.session_state["user_id"] = user.id
                st.session_state["username"] = user.username
                st.session_state["role"] = user.role
                st.success(f"Welcome, {user.username}!")
                st.experimental_rerun()
            else:
                st.error("Invalid username or password")

def guard(roles=None):
    if "user_id" not in st.session_state:
        st.stop()
    if roles and st.session_state.get("role") not in roles:
        st.warning("You do not have permission to view this section.")
        st.stop()

def topbar():
    role = st.session_state.get("role")
    u = st.session_state.get("username")
    col1, col2, col3, col4, col5 = st.columns([1.2,1,1,1,1.2])
    with col1: st.markdown(f"### 📦 WMS — **{u}** <span style='font-size:0.8em'>(**{role}**)</span>", unsafe_allow_html=True)
    with col5:
        if st.button("Logout"):
            st.session_state.clear(); st.experimental_rerun()

# ---------- Pages ----------
def page_dashboard():
    guard()
    st.title("Dashboard")
    with SessionLocal() as s:
        total_on_hand = s.scalar(select(func.coalesce(func.sum(Item.on_hand),0)))
        status_counts = {}
        for stt in ["open","picking","packed","shipped","closed"]:
            status_counts[stt] = s.scalar(select(func.count(Order.id)).where(Order.status==stt))
        # Average fulfillment time
        shipped = s.execute(select(Order).where(Order.shipped_at.is_not(None))).scalars().all()
        if shipped:
            avg_hours = round(sum([(o.shipped_at - o.created_at).total_seconds()/3600.0 for o in shipped])/len(shipped),2)
        else:
            avg_hours = None
        low_stock = s.execute(select(Item).where(Item.on_hand <= Item.reorder_point)).scalars().all()

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total On Hand", total_on_hand)
    c2.metric("Orders (Open)", status_counts.get("open",0))
    c3.metric("Orders (Shipped)", status_counts.get("shipped",0))
    c4.metric("Avg Fulfillment (hrs)", avg_hours if avg_hours is not None else "—")

    st.subheader("Low Stock Alerts")
    if low_stock:
        df = pd.DataFrame([{"SKU":i.sku, "Name":i.name, "OnHand":i.on_hand, "ROP":i.reorder_point} for i in low_stock])
        st.dataframe(df, use_container_width=True)
    else:
        st.success("No items below reorder point 🎉")

def page_inventory():
    guard()
    st.title("Inventory")
    q = st.text_input("Search (SKU / Name / Barcode)")
    with SessionLocal() as s:
        qry = select(Item)
        if q:
            like = f"%{q}%"
            qry = qry.where(or_(Item.sku.ilike(like), Item.name.ilike(like), Item.barcode.ilike(like)))
        items = s.execute(qry.order_by(Item.sku)).scalars().all()
    df = pd.DataFrame([vars(i) for i in items]) if items else pd.DataFrame(columns=["sku","name","barcode","bin_location","reorder_point","on_hand"])
    if not df.empty:
        df = df[["sku","name","barcode","bin_location","reorder_point","on_hand"]]
    st.dataframe(df, use_container_width=True)

    if st.session_state.get("role")=="admin":
        st.divider()
        st.subheader("Add Item (Admin)")
        with st.form("add_item"):
            sku = st.text_input("SKU")
            name = st.text_input("Name")
            barcode = st.text_input("Barcode")
            bin_loc = st.text_input("Bin Location")
            rop = st.number_input("Reorder Point", min_value=0, step=1, value=0)
            submitted = st.form_submit_button("Create")
        if submitted:
            if not sku or not name:
                st.error("SKU and Name are required.")
            else:
                with SessionLocal() as s:
                    if s.execute(select(Item).where(Item.sku==sku)).scalar_one_or_none():
                        st.error("SKU already exists.")
                    else:
                        s.add(Item(sku=sku, name=name, barcode=barcode or None, bin_location=bin_loc or None, reorder_point=int(rop), on_hand=0))
                        s.commit()
                        st.success("Item created.")
                        st.experimental_rerun()

def page_inbound():
    guard()
    st.title("Inbound")
    with SessionLocal() as s:
        receipts = s.execute(select(Receipt).order_by(Receipt.created_at.desc())).scalars().all()
        items = s.execute(select(Item).order_by(Item.sku)).scalars().all()

    c1, c2 = st.columns([1,2])
    with c1:
        st.subheader("Create Receipt")
        with st.form("new_receipt"):
            ref = st.text_input("Ref (e.g., RCPT-002)")
            vendor = st.text_input("Vendor")
            submitted = st.form_submit_button("Create")
        if submitted:
            if not ref:
                st.error("Ref required")
            else:
                with SessionLocal() as s:
                    if s.execute(select(Receipt).where(Receipt.ref==ref)).scalar_one_or_none():
                        st.error("Ref already exists.")
                    else:
                        s.add(Receipt(ref=ref, vendor=vendor or None))
                        s.commit()
                        st.success("Receipt created."); st.experimental_rerun()

    st.subheader("Receipts")
    for r in receipts:
        with st.expander(f"{r.ref} — {r.vendor or '—'}  [{r.status}]"):
            with SessionLocal() as s:
                r_obj = s.get(Receipt, r.id)
                r_items = s.execute(select(Item).order_by(Item.sku)).scalars().all()
            with st.form(f"add_line_{r.id}"):
                item_options = {f"{it.sku} — {it.name}": it.id for it in r_items}
                item_label = st.selectbox("Item", list(item_options.keys()))
                qty = st.number_input("Qty", min_value=1, step=1, value=1)
                if st.form_submit_button("Add Line"):
                    with SessionLocal() as s:
                        s.add(ReceiptLine(receipt_id=r.id, item_id=item_options[item_label], qty=int(qty)))
                        s.commit(); st.success("Line added."); st.experimental_rerun()

            with SessionLocal() as s:
                lines = s.execute(select(ReceiptLine).where(ReceiptLine.receipt_id==r.id)).scalars().all()
            if lines:
                df = pd.DataFrame([{"SKU":ln.item.sku, "Name":ln.item.name, "Qty":ln.qty, "Received":ln.received_qty, "LineID":ln.id} for ln in lines])
                st.dataframe(df[["SKU","Name","Qty","Received"]], use_container_width=True)
                for ln in lines:
                    with st.form(f"recv_{ln.id}", clear_on_submit=True):
                        recv = st.number_input(f"Receive qty for {ln.item.sku}", min_value=1, step=1, value=1, key=f"recv_{ln.id}_val")
                        if st.form_submit_button("Receive"):
                            with SessionLocal() as s:
                                line = s.get(ReceiptLine, ln.id)
                                item = s.get(Item, line.item_id)
                                line.received_qty += int(recv)
                                item.on_hand += int(recv)
                                s.commit()
                                st.success("Received recorded."); st.experimental_rerun()
            colA, colB = st.columns(2)
            with colA:
                if st.button("Close Receipt", key=f"close_{r.id}"):
                    with SessionLocal() as s:
                        rr = s.get(Receipt, r.id); rr.status = "received"; s.commit()
                        st.success("Receipt closed."); st.experimental_rerun()

def page_orders():
    guard()
    st.title("Orders")
    with SessionLocal() as s:
        orders = s.execute(select(Order).order_by(Order.created_at.desc())).scalars().all()
        items = s.execute(select(Item).order_by(Item.sku)).scalars().all()

    st.subheader("Create Order")
    if st.session_state.get("role") in ("admin","supervisor"):
        with st.form("new_order"):
            ref = st.text_input("Ref (e.g., ORD-002)")
            customer = st.text_input("Customer")
            if st.form_submit_button("Create"):
                if not ref:
                    st.error("Ref required")
                else:
                    with SessionLocal() as s:
                        if s.execute(select(Order).where(Order.ref==ref)).scalar_one_or_none():
                            st.error("Ref already exists.")
                        else:
                            s.add(Order(ref=ref, customer=customer or None)); s.commit()
                            st.success("Order created."); st.experimental_rerun()
    else:
        st.info("Only admin/supervisor can create orders.")

    st.subheader("All Orders")
    for o in orders:
        with st.expander(f"{o.ref} — {o.customer or '—'}  [{o.status}]"):
            with SessionLocal() as s:
                o_obj = s.get(Order, o.id)
                inv = s.execute(select(Item).order_by(Item.sku)).scalars().all()

            # Add line
            if st.session_state.get("role") in ("admin","supervisor"):
                with st.form(f"add_line_{o.id}"):
                    options = {f\"{it.sku} — {it.name} (OnHand:{it.on_hand})\": it.id for it in inv}
                    label = st.selectbox("Item", list(options.keys()))
                    qty = st.number_input("Qty", min_value=1, step=1, value=1)
                    if st.form_submit_button("Add Line"):
                        with SessionLocal() as s:
                            s.add(OrderLine(order_id=o.id, item_id=options[label], qty=int(qty)))
                            s.commit(); st.success("Line added."); st.experimental_rerun()
            else:
                st.caption("Only admin/supervisor can add lines.")

            # Lines view
            with SessionLocal() as s:
                lines = s.execute(select(OrderLine).where(OrderLine.order_id==o.id)).scalars().all()
            if lines:
                df = pd.DataFrame([{"SKU":l.item.sku, "Name":l.item.name, "Ordered":l.qty, "Picked":l.picked_qty, "Bin":l.item.bin_location, "LineID":l.id} for l in lines])
                st.dataframe(df[["SKU","Name","Ordered","Picked","Bin"]], use_container_width=True)

                # Picking (all roles including picker)
                for l in lines:
                    if st.session_state.get("role") in ("admin","supervisor","picker"):
                        with st.form(f"pick_{l.id}"):
                            pick = st.number_input(f"Pick qty for {l.item.sku}", min_value=1, step=1, value=1, key=f"pick_{o.id}_{l.id}")
                            if st.form_submit_button("Pick"):
                                with SessionLocal() as s:
                                    line = s.get(OrderLine, l.id)
                                    item = s.get(Item, line.item_id)
                                    if pick > item.on_hand:
                                        st.error("Not enough stock to pick")
                                    else:
                                        line.picked_qty += int(pick)
                                        item.on_hand -= int(pick)
                                        order = s.get(Order, o.id)
                                        order.status = "picking"; order.picked_at = datetime.utcnow()
                                        s.commit()
                                        st.success("Picked recorded."); st.experimental_rerun()
                    else:
                        st.caption("Only picker/supervisor/admin can do picking.")

            # Pack / Ship / Close
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.session_state.get("role") in ("admin","supervisor"):
                    if st.button("Pack", key=f"pack_{o.id}"):
                        with SessionLocal() as s:
                            oo = s.get(Order, o.id)
                            if any(ln.picked_qty < ln.qty for ln in oo.lines):
                                st.error("Cannot pack: some lines not fully picked.")
                            else:
                                oo.status = "packed"; s.commit(); st.success("Order packed."); st.experimental_rerun()
            with col2:
                if st.session_state.get("role") in ("admin","supervisor"):
                    with st.form(f"ship_{o.id}"):
                        carrier = st.text_input("Carrier")
                        tracking = st.text_input("Tracking #")
                        if st.form_submit_button("Ship"):
                            with SessionLocal() as s:
                                oo = s.get(Order, o.id)
                                s.add(Shipment(order_id=oo.id, carrier=carrier or None, tracking_no=tracking or None))
                                oo.status = "shipped"; oo.shipped_at = datetime.utcnow(); s.commit()
                                st.success("Shipment created."); st.experimental_rerun()
            with col3:
                if st.session_state.get("role") in ("admin","supervisor"):
                    if st.button("Close", key=f"close_{o.id}"):
                        with SessionLocal() as s:
                            oo = s.get(Order, o.id)
                            oo.status = "closed"; s.commit(); st.success("Order closed."); st.experimental_rerun()

def page_users():
    guard(["admin"])
    st.title("Users (Admin)")
    with SessionLocal() as s:
        users = s.execute(select(User).order_by(User.username)).scalars().all()
    df = pd.DataFrame([{"ID":u.id,"Username":u.username,"Role":u.role,"Created":u.created_at.strftime("%Y-%m-%d %H:%M")} for u in users])
    st.dataframe(df, use_container_width=True)

    st.subheader("Create User")
    with st.form("create_user"):
        username = st.text_input("Username")
        role = st.selectbox("Role", ["admin","supervisor","picker"], index=2)
        password = st.text_input("Initial Password", type="password")
        submitted = st.form_submit_button("Create")
    if submitted:
        if not username or not password:
            st.error("Username and password required.")
        else:
            with SessionLocal() as s:
                if s.execute(select(User).where(User.username==username)).scalar_one_or_none():
                    st.error("Username already exists.")
                else:
                    nu = User(username=username, role=role); nu.set_password(password); s.add(nu); s.commit()
                    st.success("User created."); st.experimental_rerun()

    st.subheader("Edit / Reset / Delete")
    with SessionLocal() as s:
        users = s.execute(select(User).order_by(User.username)).scalars().all()
    user_map = {f"{u.username} ({u.role})": u.id for u in users}
    if user_map:
        sel = st.selectbox("Select User", list(user_map.keys()))
        uid = user_map[sel]
        with SessionLocal() as s:
            u = s.get(User, uid)
        new_username = st.text_input("New Username", value=u.username, key=f"nu_{uid}")
        new_role = st.selectbox("New Role", ["admin","supervisor","picker"], index=["admin","supervisor","picker"].index(u.role), key=f"nr_{uid}")
        col1,col2,col3 = st.columns(3)
        with col1:
            if st.button("Save"):
                with SessionLocal() as s:
                    uu = s.get(User, uid)
                    # uniqueness check
                    exists = s.execute(select(User).where(User.username==new_username, User.id!=uid)).scalar_one_or_none()
                    if exists:
                        st.error("Username is already taken.")
                    else:
                        uu.username = new_username; uu.role = new_role; s.commit(); st.success("User updated."); st.experimental_rerun()
        with col2:
            new_pw = st.text_input("Reset Password", type="password", key=f"rpw_{uid}")
            if st.button("Reset"):
                if not new_pw:
                    st.error("New password required.")
                else:
                    with SessionLocal() as s:
                        uu = s.get(User, uid); uu.set_password(new_pw); s.commit(); st.success("Password reset."); st.experimental_rerun()
        with col3:
            if st.button("Delete"):
                if uid == st.session_state.get("user_id"):
                    st.error("You cannot delete your own account.")
                else:
                    with SessionLocal() as s:
                        uu = s.get(User, uid); s.delete(uu); s.commit(); st.success("User deleted."); st.experimental_rerun()

def page_change_password():
    guard()
    st.title("Change Password")
    with st.form("change_pw"):
        old = st.text_input("Old Password", type="password")
        new = st.text_input("New Password", type="password")
        submitted = st.form_submit_button("Update")
    if submitted:
        uid = st.session_state.get("user_id")
        with SessionLocal() as s:
            u = s.get(User, uid)
            if not u.check_password(old):
                st.error("Old password incorrect.")
            elif not new:
                st.error("New password cannot be empty.")
            else:
                u.set_password(new); s.commit(); st.success("Password changed.")

# ---------- App ----------
def main():
    if "user_id" not in st.session_state:
        st.sidebar.title("WMS Streamlit")
        st.sidebar.info("Please log in to continue.")
        login_form()
        st.stop()

    topbar()
    st.sidebar.title("Navigation")
    pages = {
        "Dashboard": page_dashboard,
        "Inventory": page_inventory,
        "Inbound": page_inbound,
        "Orders": page_orders,
        "Change Password": page_change_password
    }
    if st.session_state.get("role") == "admin":
        pages["Users (Admin)"] = page_users
    choice = st.sidebar.radio("Go to", list(pages.keys()), label_visibility="collapsed")
    pages[choice]()

if __name__ == "__main__":
    main()
