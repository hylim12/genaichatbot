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
        color: #212529;  /* Dark text color for better visibility */
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
</style>
""", unsafe_allow_html=True)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Configuration with fallback handling
try:
    # Load environment variables explicitly
    load_dotenv(verbose=True)  # Enable verbose mode to see which variables are loaded
    
    S3_BUCKET = os.getenv('S3_BUCKET_NAME', 'cacheme-documents')
    S3_REGION = os.getenv('AWS_REGION', 'ap-southeast-1')  # Updated to match AWS console region
    QUERY_LAMBDA_ARN = os.getenv('QUERY_LAMBDA_ARN', 'arn:aws:lambda:ap-southeast-1:339712974969:function:query-lambda')
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    OPENSEARCH_ENDPOINT = os.getenv('OPENSEARCH_ENDPOINT')
    
    # Debug information (will be removed in production)
    st.sidebar.markdown("### Debug Information")
    st.sidebar.text(f"Region: {S3_REGION}")
    st.sidebar.text(f"Bucket: {S3_BUCKET}")
    st.sidebar.text(f"Access Key ID: {'Set' if AWS_ACCESS_KEY_ID else 'Not Set'}")
    st.sidebar.text(f"Secret Key: {'Set' if AWS_SECRET_ACCESS_KEY else 'Not Set'}")
    
    if not (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
        raise ValueError("AWS credentials not found in environment variables")
except Exception as e:
    st.error(f"Error loading environment variables: {str(e)}. Please check your .env file.")

# Initialize AWS clients
try:
    # Create AWS clients with credentials
    sts = boto3.client(
        'sts',
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    # Verify credentials
    identity = sts.get_caller_identity()
    st.sidebar.success(f"✅ AWS Credentials Valid\nAccount: {identity['Account']}")
    
    # Initialize other clients
    s3_client = boto3.client(
        's3',
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    lambda_client = boto3.client(
        'lambda',
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
except Exception as e:
    error_message = str(e)
    if 'InvalidAccessKeyId' in error_message:
        st.error("❌ Invalid AWS Access Key ID. Please check if your credentials are correct and not expired.")
    elif 'SignatureDoesNotMatch' in error_message:
        st.error("❌ Invalid AWS Secret Access Key. Please check if your secret key is correct.")
    elif 'ExpiredToken' in error_message:
        st.error("❌ AWS credentials have expired. Please refresh your credentials.")
    else:
        st.error(f"❌ Failed to initialize AWS clients: {error_message}")
    s3_client = None
    lambda_client = None

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
    Upload file directly to S3 and trigger ingestion
    
    Args:
        file_content: File content as bytes
        filename: Name of the file
        
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
            S3_BUCKET, 
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
                "bucket": S3_BUCKET,
                "filename": filename
            }
        }
    except ClientError as e:
        error_msg = str(e)
        if 'AccessDenied' in error_msg:
            return {"success": False, "error": "Access denied to S3. Please check your AWS credentials and permissions."}
        elif 'NoSuchBucket' in error_msg:
            return {"success": False, "error": f"S3 bucket '{S3_BUCKET}' not found. Please check your configuration."}
        else:
            return {"success": False, "error": f"S3 upload failed: {error_msg}"}

def send_chat_message(message: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Send chat message to Query Lambda with retry logic
    
    Args:
        message: User's question/message
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
                FunctionName=QUERY_LAMBDA_ARN,
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

def display_chat_message(message: Dict[str, Any], is_user: bool = False):
    """
    Display a chat message with proper styling
    
    Args:
        message: Message content
        is_user: Whether this is a user message
    """
    try:
        if is_user:
            st.markdown(f"""
            <div class="chat-message user-message">
                <strong>You:</strong> {message['content']}
            </div>
            """, unsafe_allow_html=True)
        else:
            try:
                # Try to parse as JSON if it's a string and looks like JSON
                if isinstance(message['content'], str) and message['content'].strip().startswith('{'):
                    response_data = json.loads(message['content'])
                else:
                    response_data = message['content'] if isinstance(message['content'], dict) else {'response': message['content']}
                
                st.markdown(f"""
                <div class="chat-message ai-message">
                    <strong>AI Assistant:</strong> {response_data.get('response', 'No response received')}
                </div>
                """, unsafe_allow_html=True)
                
                # Display document snippets if available
                snippets = response_data.get('snippets', [])
                if snippets:
                    st.markdown("**Relevant Document Snippets:**")
                    for snippet in snippets:
                        st.markdown(f"""
                        <div class="document-snippet">
                            <strong>From:</strong> {snippet.get('source', 'Unknown document')}<br>
                            {snippet.get('text', '')}
                        </div>
                        """, unsafe_allow_html=True)
            except json.JSONDecodeError:
                # If JSON parsing fails, display the content as is
                st.markdown(f"""
                <div class="chat-message ai-message">
                    <strong>AI Assistant:</strong> {message['content']}
                </div>
                """, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Error displaying message: {str(e)}")

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
                    result = upload_file_to_s3(file_content, uploaded_file.name)
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
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Add custom CSS for file list
        st.markdown("""
        <style>
        .file-list-container {
            background-color: #2d3436;
            border-radius: 10px;
            padding: 15px;
            margin: 10px 0;
        }
        .file-item {
            background-color: #34495e;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
        }
        .file-name {
            color: #3498db;
            font-size: 1.1em;
            font-weight: bold;
        }
        .file-details {
            color: #bdc3c7;
            font-size: 0.9em;
            margin-top: 5px;
        }
        .success-icon {
            color: #2ecc71;
        }
        </style>
        """, unsafe_allow_html=True)

        # Display uploaded files
        if st.session_state.uploaded_files:
            st.markdown("### 📚 Document Library")
            
            for file_info in st.session_state.uploaded_files:
                st.markdown(f"""
                <div class="file-list-container">
                    <div class="file-item">
                        <div class="file-name">
                            <span class="success-icon">✓</span> {file_info['name']}
                        </div>
                        <div class="file-details">
                            📊 Size: {file_info['size']:,} bytes<br>
                            🕒 Uploaded: {file_info['upload_time']}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        # Document preview section
        if uploaded_file is not None:
            st.markdown("### 👁️ Document Preview")
            preview_container = st.container()
            with preview_container:
                st.markdown("""
                <style>
                    .pdf-preview {
                        background-color: #2d3436;
                        border-radius: 10px;
                        padding: 20px;
                        margin: 10px 0;
                    }
                    .file-info {
                        color: #dfe6e9;
                        font-family: monospace;
                        margin-bottom: 10px;
                    }
                    .preview-header {
                        color: #74b9ff;
                        font-size: 1.1em;
                        margin-bottom: 15px;
                    }
                </style>
                """, unsafe_allow_html=True)
                
                st.markdown('<div class="pdf-preview">', unsafe_allow_html=True)
                st.markdown('<div class="preview-header">📄 Document Information</div>', unsafe_allow_html=True)
                
                # Display file information in a formatted way
                st.markdown(f"""
                <div class="file-info">
                    <strong>File Name:</strong> {uploaded_file.name}<br>
                    <strong>Size:</strong> {uploaded_file.size:,} bytes<br>
                    <strong>Type:</strong> {uploaded_file.type}<br>
                    <strong>Status:</strong> Ready for processing
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        # Sidebar chat interface
        st.markdown("### 💬 Chat Interface")
        
        # Chat input and guidance
        if not st.session_state.uploaded_files:
            st.warning("👋 Please upload some documents first before asking questions.")
            
        st.markdown("""
        **Tips for better results:**
        - Be specific in your questions
        - Mention key terms from your documents
        - Ask one question at a time
        """)
        
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
            
            # Send to Query Lambda and get response
            status_placeholder = st.empty()
            with status_placeholder:
                with st.spinner("🔍 Searching through documents..."):
                    result = send_chat_message(user_input)
                    
                    if result["success"]:
                        try:
                            # Handle different response formats
                            if isinstance(result["data"], str):
                                try:
                                    response_data = json.loads(result["data"])
                                except json.JSONDecodeError:
                                    # If it's not valid JSON, treat it as a plain string response
                                    response_data = {"response": result["data"], "snippets": []}
                            else:
                                response_data = result["data"]
                            
                            # Ensure response_data is a dictionary
                            if not isinstance(response_data, dict):
                                response_data = {"response": str(response_data), "snippets": []}
                                
                            # Check if we have any relevant snippets
                            snippets = response_data.get("snippets", [])
                            if snippets:
                                status_placeholder.success("📚 Found relevant information!")
                            else:
                                status_placeholder.info("🔍 No exact matches found, but I'll try to help.")
                            
                            ai_response = {
                                "content": response_data,
                                "timestamp": datetime.now().strftime("%H:%M:%S"),
                                "type": "ai",
                                "snippets": snippets
                            }
                            st.session_state.chat_history.append(ai_response)
                        except json.JSONDecodeError:
                            status_placeholder.warning("⚠️ Received unexpected response format")
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
                        status_placeholder.error("❌ Error processing your request")
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
