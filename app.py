import streamlit as st
import boto3
from botocore.exceptions import ClientError
from io import BytesIO
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
        color: #212529;
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
    .success-banner {
        background-color: #27ae60;
        color: white;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
        text-align: center;
    }
    .info-banner {
        background-color: #3498db;
        color: white;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
        text-align: center;
    }
    .unified-chat-container {
        max-height: 600px;
        overflow-y: auto;
        padding: 1rem;
        background-color: #f8f9fa;
        border-radius: 8px;
        border: 1px solid #dee2e6;
        margin-bottom: 1rem;
        display: flex;
        flex-direction: column;
    }
    .chat-messages {
        flex: 1;
        overflow-y: auto;
    }
    .chat-input-section {
        background-color: #ffffff;
        border-top: 1px solid #dee2e6;
        padding: 1rem;
        border-radius: 0 0 8px 8px;
        margin-top: 1rem;
    }
    .message-timestamp {
        font-size: 0.8rem;
        opacity: 0.7;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Configuration - Load from environment variables
def load_config():
    """Load configuration from environment variables"""
    # Try to load from .env file if in development
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        # dotenv not available in production, use system env vars
        pass
    
    config = {
        'S3_BUCKET': os.getenv('S3_BUCKET_NAME', 'cacheme-documents'),
        'S3_REGION': os.getenv('AWS_REGION', 'ap-southeast-1'),
        'QUERY_LAMBDA_ARN': os.getenv('QUERY_LAMBDA_ARN', 'arn:aws:lambda:ap-southeast-1:339712974969:function:query-lambda'),
        'AWS_ACCESS_KEY_ID': os.getenv('AWS_ACCESS_KEY_ID'),
        'AWS_SECRET_ACCESS_KEY': os.getenv('AWS_SECRET_ACCESS_KEY'),
        'OPENSEARCH_ENDPOINT': os.getenv('OPENSEARCH_ENDPOINT')
    }
    return config

# Initialize AWS clients
@st.cache_resource
def initialize_aws_clients():
    """Initialize AWS clients with caching"""
    config = load_config()
    
    try:
        # Create AWS session - will use IAM roles if available, otherwise use access keys
        session_kwargs = {'region_name': config['S3_REGION']}
        
        if config['AWS_ACCESS_KEY_ID'] and config['AWS_SECRET_ACCESS_KEY']:
            session_kwargs.update({
                'aws_access_key_id': config['AWS_ACCESS_KEY_ID'],
                'aws_secret_access_key': config['AWS_SECRET_ACCESS_KEY']
            })
        
        session = boto3.Session(**session_kwargs)
        
        # Initialize clients
        s3_client = session.client('s3')
        lambda_client = session.client('lambda')
        
        # Test connection
        try:
            sts_client = session.client('sts')
            identity = sts_client.get_caller_identity()
            return s3_client, lambda_client, config, True, f"Connected to AWS Account: {identity['Account']}"
        except Exception as e:
            return None, None, config, False, f"AWS connection failed: {str(e)}"
            
    except Exception as e:
        return None, None, config, False, f"Failed to initialize AWS clients: {str(e)}"

# Initialize session state
def initialize_session_state():
    """Initialize session state variables"""
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'upload_status' not in st.session_state:
        st.session_state.upload_status = {}

def upload_file_to_s3(file_content: bytes, filename: str, s3_client, config: dict) -> Dict[str, Any]:
    """
    Upload file directly to S3 and trigger ingestion
    
    Args:
        file_content: File content as bytes
        filename: Name of the file
        s3_client: Initialized S3 client
        config: Configuration dictionary
        
    Returns:
        Response status
    """
    if s3_client is None:
        return {"success": False, "error": "S3 client not initialized. Please check your AWS credentials."}
    
    try:
        # Generate a unique S3 key for the file
        s3_key = f"uploads/{uuid.uuid4()}_{filename}"
        
        # Upload to S3
        s3_client.upload_fileobj(
            BytesIO(file_content), 
            config['S3_BUCKET'], 
            s3_key, 
            ExtraArgs={
                'ContentType': 'application/pdf',
                'Metadata': {
                    'filename': filename,
                    'upload_time': datetime.now().isoformat()
                }
            }
        )
        
        # Wait briefly to ensure S3 consistency
        time.sleep(1)
        
        return {
            "success": True, 
            "data": {
                "s3_key": s3_key,
                "bucket": config['S3_BUCKET'],
                "filename": filename
            }
        }
    except ClientError as e:
        error_msg = str(e)
        if 'AccessDenied' in error_msg:
            return {"success": False, "error": "Access denied to S3. Please check your AWS credentials and permissions."}
        elif 'NoSuchBucket' in error_msg:
            return {"success": False, "error": f"S3 bucket '{config['S3_BUCKET']}' not found. Please check your configuration."}
        else:
            return {"success": False, "error": f"S3 upload failed: {error_msg}"}

def send_chat_message(message: str, lambda_client, config: dict, max_retries: int = 3) -> Dict[str, Any]:
    """
    Send chat message to Query Lambda with retry logic
    
    Args:
        message: User's question/message
        lambda_client: Initialized Lambda client
        config: Configuration dictionary
        max_retries: Maximum number of retry attempts
        
    Returns:
        Response from the Query Lambda
    """
    if lambda_client is None:
        return {
            "success": True,
            "data": {
                "response": "I'm not connected to AWS services right now. Please check your AWS credentials and region settings.",
                "snippets": []
            }
        }

    for attempt in range(max_retries):
        try:
            payload = {"query": message}
            response = lambda_client.invoke(
                FunctionName=config['QUERY_LAMBDA_ARN'],
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            response_body = json.loads(response['Payload'].read().decode('utf-8'))
            
            if 'statusCode' in response_body and response_body['statusCode'] == 200:
                return {"success": True, "data": response_body['body']}
            
            # Handle specific error cases that might be retryable
            error_msg = response_body.get('body', {}).get('error', 'Unknown error')
            if any(retryable in error_msg.lower() for retryable in ['timeout', 'throttle', 'temporary']):
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 0.5  # Exponential backoff
                    time.sleep(wait_time)
                    continue
                    
            # Non-retryable error or max retries reached
            return {
                "success": True,
                "data": {
                    "response": f"I encountered an error: {error_msg}. Please try again or rephrase your question.",
                    "snippets": []
                }
            }
            
        except ClientError as e:
            error_message = str(e)
            
            # Handle specific AWS errors
            if 'UnrecognizedClientException' in error_message:
                return {
                    "success": True,
                    "data": {
                        "response": "Invalid AWS credentials. Please check your AWS access key and secret key.",
                        "snippets": []
                    }
                }
            elif 'AccessDeniedException' in error_message:
                return {
                    "success": True,
                    "data": {
                        "response": "Access denied. Please check your AWS IAM permissions.",
                        "snippets": []
                    }
                }
            elif any(retryable in error_message.lower() for retryable in ['timeout', 'throttle', 'temporary']):
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 0.5
                    time.sleep(wait_time)
                    continue
            
            return {
                "success": True,
                "data": {
                    "response": f"AWS service error: {error_message}",
                    "snippets": []
                }
            }
            
        except json.JSONDecodeError:
            return {
                "success": True,
                "data": {
                    "response": "Received invalid response format. Please try again.",
                    "snippets": []
                }
            }
            
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + 0.5
                time.sleep(wait_time)
                continue
                
            return {
                "success": True,
                "data": {
                    "response": f"An unexpected error occurred: {str(e)}",
                    "snippets": []
                }
            }
    
    return {
        "success": True,
        "data": {
            "response": "Request failed after multiple attempts. Please try again later.",
            "snippets": []
        }
    }

def main():
    """Main application function"""
    initialize_session_state()
    
    # Initialize AWS clients
    s3_client, lambda_client, config, aws_connected, aws_status = initialize_aws_clients()
    
    # Show connection status in sidebar
    if aws_connected:
        st.sidebar.success(f"✅ {aws_status}")
    else:
        st.sidebar.error(f"❌ {aws_status}")
    
    # Header section
    st.markdown('<h1 class="main-header">📚 Internal Document Search Chatbot</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Upload your internal documents and ask questions using natural language</p>', unsafe_allow_html=True)
    
    # Main layout with sidebar
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Document upload section
        st.markdown("### 📄 Document Upload")
        
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
            if st.button("📤 Upload to System", type="primary", disabled=not aws_connected):
                if not aws_connected:
                    st.error("❌ Cannot upload: AWS connection not available")
                else:
                    progress_placeholder = st.empty()
                    status_placeholder = st.empty()
                    
                    with progress_placeholder.container():
                        progress_bar = st.progress(0)
                        status_placeholder.text("Preparing file for upload...")
                        time.sleep(0.5)
                        progress_bar.progress(25)
                        
                        # Upload file
                        file_content = uploaded_file.read()
                        status_placeholder.text("Uploading to S3...")
                        result = upload_file_to_s3(file_content, uploaded_file.name, s3_client, config)
                        progress_bar.progress(50)
                        
                        if result["success"]:
                            status_placeholder.text("Processing document...")
                            progress_bar.progress(75)
                            
                            # Add to session state
                            st.session_state.uploaded_files.append({
                                "name": uploaded_file.name,
                                "size": uploaded_file.size,
                                "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "status": "processing",
                                "s3_key": result["data"]["s3_key"]
                            })
                            
                            # Wait briefly to simulate processing time and allow ingestion lambda to start
                            time.sleep(2)
                            progress_bar.progress(100)
                            status_placeholder.text("Document ready!")
                            
                            st.success("✅ Document uploaded and processed successfully!")
                            st.info("📝 You can now ask questions about this document.")
                            
                            # Update final status
                            st.session_state.upload_status[uploaded_file.name] = "success"
                        else:
                            st.session_state.upload_status[uploaded_file.name] = "error"
                            st.error(f"❌ Upload failed: {result['error']}")
        
        # PDF Viewer section (simplified for deployment)
        if uploaded_file is not None:
            st.markdown("### 📄 PDF Viewer")
            uploaded_file.seek(0)
            pdf_bytes = uploaded_file.read()
            st.info(f"📄 **{uploaded_file.name}** - {uploaded_file.size:,} bytes")
            
            # Simple download option
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name=uploaded_file.name,
                mime="application/pdf"
            )
    
    with col2:
        # Chat interface
        st.markdown("### 💬 Ask a Question")
        
        # Unified scrollable chatbox
        st.markdown('<div class="unified-chat-container">', unsafe_allow_html=True)
        
        if not st.session_state.chat_history:
            st.info("👋 Start a conversation by asking a question about your documents!")
        else:
            for message in st.session_state.chat_history:
                if message["type"] == "user":
                    st.markdown(f"""
                    <div class="chat-message user-message">
                        <div class="message-timestamp">You • {message.get('timestamp', '')}</div>
                        <strong>{message['content']}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    # AI message with snippets
                    try:
                        if isinstance(message['content'], str) and message['content'].strip().startswith('{'):
                            response_data = json.loads(message['content'])
                        else:
                            response_data = message['content'] if isinstance(message['content'], dict) else {'response': message['content']}

                        response_text = response_data.get('response', 'No response received')
                        snippets = response_data.get('snippets', [])

                        st.markdown(f"""
                        <div class="chat-message ai-message">
                            <div class="message-timestamp">AI Assistant • {message.get('timestamp', '')}</div>
                            <strong>{response_text}</strong>
                        </div>
                        """, unsafe_allow_html=True)

                        # Display document snippets if available
                        if snippets:
                            st.markdown("**📄 Relevant Document Snippets:**")
                            for snippet in snippets:
                                st.markdown(f"""
                                <div class="document-snippet">
                                    <strong>From:</strong> {snippet.get('source', 'Unknown document')}<br>
                                    {snippet.get('text', '')}
                                </div>
                                """, unsafe_allow_html=True)
                    except json.JSONDecodeError:
                        st.markdown(f"""
                        <div class="chat-message ai-message">
                            <div class="message-timestamp">AI Assistant • {message.get('timestamp', '')}</div>
                            <strong>{message['content']}</strong>
                        </div>
                        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)
        
        # Input section
        user_input = st.text_area(
            "Ask a question about your documents:",
            height=80,
            placeholder="e.g., What are the safety guidelines for equipment maintenance?",
            key="user_input",
            label_visibility="collapsed"
        )
        
        # Send and New Chat buttons
        col_send, col_new_chat = st.columns([1, 1])
        with col_send:
            send_button = st.button("Send", type="primary", disabled=not user_input.strip() or not aws_connected)

        with col_new_chat:
            new_chat_button = st.button("New Chat")

        # Handle new chat button
        if new_chat_button:
            st.session_state.chat_history = []
            st.rerun()
        
        # Handle send button
        if send_button and user_input.strip() and aws_connected:
            # Add user message to history
            user_message = {
                "content": user_input,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": "user"
            }
            st.session_state.chat_history.append(user_message)
            
            # Send to Query Lambda and get response
            with st.spinner("🔍 Searching through documents..."):
                result = send_chat_message(user_input, lambda_client, config)
                
                if result["success"]:
                    try:
                        if isinstance(result["data"], str):
                            response_data = json.loads(result["data"])
                        else:
                            response_data = result["data"]
                            
                        ai_response = {
                            "content": result["data"],
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "type": "ai"
                        }
                        st.session_state.chat_history.append(ai_response)
                    except json.JSONDecodeError:
                        error_response = {
                            "content": {
                                "response": "I received an invalid response format. Please try asking your question again.",
                                "snippets": []
                            },
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "type": "ai"
                        }
                        st.session_state.chat_history.append(error_response)
                else:
                    error_response = {
                        "content": {
                            "response": f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
                            "snippets": []
                        },
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "type": "ai"
                    }
                    st.session_state.chat_history.append(error_response)
            
            st.rerun()
    
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
