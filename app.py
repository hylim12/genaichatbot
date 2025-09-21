import streamlit as st
import boto3
from botocore.exceptions import ClientError
from io import BytesIO
import requests
import json
from datetime import datetime
import time
import os
import uuid
from typing import List, Dict, Any

# Page configuration
st.set_page_config(
    page_title="Internal Document Search Chatbot",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .upload-section {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border: 2px dashed #dee2e6;
        margin-bottom: 2rem;
    }
    .file-list {
        background-color: #e8f4fd;
        padding: 1rem;
        border-radius: 8px;
        margin-top: 1rem;
    }
    .chat-message {
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 10px;
    }
    .user-message {
        background-color: #007bff;
        color: white;
        margin-left: 20%;
    }
    .ai-message {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        margin-right: 20%;
    }
    .document-snippet {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 5px;
        padding: 0.8rem;
        margin: 0.5rem 0;
        font-style: italic;
    }
    .error-message {
        background-color: #f8d7da;
        color: #721c24;
        padding: 1rem;
        border-radius: 5px;
        border: 1px solid #f5c6cb;
    }
    .success-message {
        background-color: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 5px;
        border: 1px solid #c3e6cb;
    }
</style>
""", unsafe_allow_html=True)

# Configuration with fallback handling
try:
    S3_BUCKET = os.environ.get('S3_BUCKET_NAME', st.secrets.get('S3_BUCKET_NAME', 'cacheme-documents'))
    S3_REGION = os.environ.get('AWS_REGION', st.secrets.get('AWS_REGION', 'ap-southeast-5'))
    API_BASE_URL = os.environ.get('API_BASE_URL', st.secrets.get('API_BASE_URL', 'http://localhost:8000'))
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', st.secrets.get('AWS_ACCESS_KEY_ID'))
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', st.secrets.get('AWS_SECRET_ACCESS_KEY'))
except Exception as e:
    st.error(f"Error loading secrets or environment variables: {str(e)}. Using defaults or environment variables. Please configure secrets.toml or set environment variables.")
    S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'cacheme-documents')
    S3_REGION = os.environ.get('AWS_REGION', 'ap-southeast-5')
    API_BASE_URL = os.environ.get('API_BASE_URL', 'http://localhost:8000')
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

UPLOAD_ENDPOINT = f"{API_BASE_URL}/upload"
CHAT_ENDPOINT = f"{API_BASE_URL}/chat"

# Initialize S3 client with fallbacks
try:
    s3_client = boto3.client(
        's3',
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
except Exception as e:
    st.error(f"Failed to initialize S3 client: {str(e)}. Please check your AWS credentials and region.")
    s3_client = None

# Initialize session state
def initialize_session_state():
    """Initialize session state variables"""
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'upload_status' not in st.session_state:
        st.session_state.upload_status = {}

def upload_file_to_s3(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Upload file directly to S3
    
    Args:
        file_content: File content as bytes
        filename: Name of the file
        
    Returns:
        Response status
    """
    if s3_client is None:
        return {"success": False, "error": "S3 client not initialized"}
    try:
        s3_key = f"uploads/{uuid.uuid4()}_{filename}"
        s3_client.upload_fileobj(BytesIO(file_content), S3_BUCKET, s3_key, ExtraArgs={'ContentType': 'application/pdf'})
        return {"success": True, "data": {"s3_key": s3_key}}
    except ClientError as e:
        return {"success": False, "error": f"S3 upload failed: {str(e)}"}

def send_chat_message(message: str) -> Dict[str, Any]:
    """
    Send chat message to backend API
    
    Args:
        message: User's question/message
        
    Returns:
        Response from the API
    """
    try:
        payload = {"message": message}
        response = requests.post(CHAT_ENDPOINT, json=payload, timeout=30)
        
        if response.status_code == 200:
            return {"success": True, "data": response.json()}
        else:
            return {"success": False, "error": f"Chat failed: {response.status_code}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Connection error: {str(e)}"}

def display_chat_message(message: Dict[str, Any], is_user: bool = False):
    """
    Display a chat message with proper styling
    
    Args:
        message: Message content
        is_user: Whether this is a user message
    """
    if is_user:
        st.markdown(f"""
        <div class="chat-message user-message">
            <strong>You:</strong> {message['content']}
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="chat-message ai-message">
            <strong>AI Assistant:</strong> {message['content']}
        </div>
        """, unsafe_allow_html=True)
        
        # Display document snippets if available
        if 'snippets' in message and message['snippets']:
            st.markdown("**Relevant Document Snippets:**")
            for snippet in message['snippets']:
                st.markdown(f"""
                <div class="document-snippet">
                    <strong>From:</strong> {snippet.get('source', 'Unknown document')}<br>
                    {snippet.get('text', '')}
                </div>
                """, unsafe_allow_html=True)

def main():
    """Main application function"""
    initialize_session_state()
    
    # Header section
    st.markdown('<h1 class="main-header">📚 Internal Document Search Chatbot</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Upload your internal documents and ask questions using natural language</p>', unsafe_allow_html=True)
    
    # Main layout with sidebar
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Document upload section
        st.markdown("### 📄 Document Upload")
        st.markdown('<div class="upload-section">', unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "Choose a PDF file",
            type=['pdf'],
            help="Upload internal documents like guidelines, manuals, and policies"
        )
        
        if uploaded_file is not None:
            # Display file info
            st.write(f"**File:** {uploaded_file.name}")
            st.write(f"**Size:** {uploaded_file.size:,} bytes")
            
            # Upload button
            if st.button("📤 Upload to System", type="primary"):
                with st.spinner("Uploading file..."):
                    file_content = uploaded_file.read()
                    result = upload_file_to_s3(file_content, uploaded_file.name)
                    
                    if result["success"]:
                        st.session_state.uploaded_files.append({
                            "name": uploaded_file.name,
                            "size": uploaded_file.size,
                            "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "status": "success",
                            "s3_key": result["data"]["s3_key"]
                        })
                        st.session_state.upload_status[uploaded_file.name] = "success"
                        st.success(f"✅ Successfully uploaded {uploaded_file.name} to S3")
                    else:
                        st.session_state.upload_status[uploaded_file.name] = "error"
                        st.error(f"❌ Upload failed: {result['error']}")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Display uploaded files
        if st.session_state.uploaded_files:
            st.markdown("### 📋 Uploaded Files")
            st.markdown('<div class="file-list">', unsafe_allow_html=True)
            
            for file_info in st.session_state.uploaded_files:
                status_icon = "✅" if file_info["status"] == "success" else "❌"
                st.write(f"{status_icon} **{file_info['name']}**")
                st.write(f"   Size: {file_info['size']:,} bytes")
                st.write(f"   Uploaded: {file_info['upload_time']}")
                st.write(f"   S3 Key: {file_info['s3_key']}")
                st.write("---")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Document preview section
        if uploaded_file is not None:
            st.markdown("### 👁️ Document Preview")
            st.info("📄 PDF preview would be displayed here. For now, showing file information.")
            st.json({
                "filename": uploaded_file.name,
                "size": f"{uploaded_file.size:,} bytes",
                "type": uploaded_file.type
            })
    
    with col2:
        # Sidebar chat interface
        st.markdown("### 💬 Chat Interface")
        
        # Chat input
        user_input = st.text_area(
            "Ask a question about your documents:",
            height=100,
            placeholder="e.g., What are the safety guidelines for equipment maintenance?"
        )
        
        col_send, col_clear = st.columns([1, 1])
        
        with col_send:
            send_button = st.button("🚀 Send", type="primary", disabled=not user_input.strip())
        
        with col_clear:
            clear_button = st.button("🗑️ Clear Chat")
        
        # Handle clear chat
        if clear_button:
            st.session_state.chat_history = []
            st.rerun()
        
        # Handle send message
        if send_button and user_input.strip():
            # Add user message to history
            user_message = {
                "content": user_input,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": "user"
            }
            st.session_state.chat_history.append(user_message)
            
            # Send to backend and get response
            with st.spinner("🤔 Thinking..."):
                result = send_chat_message(user_input)
                
                if result["success"]:
                    ai_response = {
                        "content": result["data"].get("response", "No response received"),
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "type": "ai",
                        "snippets": result["data"].get("snippets", [])
                    }
                    st.session_state.chat_history.append(ai_response)
                else:
                    error_response = {
                        "content": f"Sorry, I encountered an error: {result['error']}",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "type": "ai",
                        "snippets": []
                    }
                    st.session_state.chat_history.append(error_response)
            
            st.rerun()
        
        # Display chat history
        st.markdown("### 💭 Conversation History")
        
        if not st.session_state.chat_history:
            st.info("👋 Start a conversation by asking a question about your documents!")
        else:
            # Create a scrollable container for chat history
            chat_container = st.container()
            
            with chat_container:
                for message in st.session_state.chat_history:
                    display_chat_message(message, is_user=(message["type"] == "user"))
                    st.write("")  # Add spacing between messages
    
    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666; padding: 1rem;'>
            <p>🔧 Internal Document Search Chatbot | Built with Streamlit</p>
            <p>For manufacturing employees to easily search guidelines, manuals, and policies</p>
        </div>
        """, 
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
