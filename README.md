# Grocery Share App - Backend API



## Overview  
| Description                                                                 | Icon                                                                 |
|-----------------------------------------------------------------------------|----------------------------------------------------------------------|
| This is the backend REST API built with Django, designed to support the Grocery Share App. It handles API endpoints for managing grocery-related data and is intended to be used in conjunction with the frontend Grocery Share App (to be pushed to GitHub separately). | ![Grocery Share App Icon](appIcon.jpg) |


## Demo Video
Watch a demonstration of the project in action:

<iframe width="560" height="315" src="https://www.youtube.com/embed/23S-vV6ZRFo" title="Project Demo Video" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>

## Prerequisites  
- Python 3.x  
- pip (Python package manager)  
- Git (for version control)  
- PostgreSQL (or compatible database as per `.env` configuration)  

## Setup Instructions  

1. **Clone the Repository**
   ```bash
   git clone https://github.com/alan5543/Grocery-Share-API.git
   cd Grocery-Share-API
   ```

2. **Create and Activate Virtual Environment**
   ```bash
   python3 -m venv django-env
   source django-env/bin/activate  # On macOS/Linux
   django-env\Scripts\activate     # On Windows
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables**
   Create a `.env` file in the project root directory and add the following variables:
   ```
   GEMINI_API_KEY=your_gemini_api_key_here
   SECRET_KEY=your_django_secret_key_here
   DJANGO_DEBUG=True  # Set to False for production
   DB_ENGINE=django.db.backends.postgresql
   DB_NAME=your_database_name
   DB_USER=your_database_user
   DB_PASSWORD=your_database_password
   DB_HOST=aws-0-ca-central-1.pooler.supabase.com
   DB_PORT=6543
   ```
   - Replace `your_gemini_api_key_here`, `your_django_secret_key_here`, `your_database_name`, `your_database_user`, and `your_database_password` with appropriate values.
   - Keep `.env` out of version control (it’s ignored by `.gitignore`).

5. **Apply Migrations**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

6. **Run the Server**
   ```bash
   python manage.py runserver
   ```

- **Using ngrok (Public Access):**
  1. Download and install ngrok from [ngrok.com](https://ngrok.com/).
  2. Start ngrok with the following command in a new terminal window:
      ```bash
      ngrok http 8000
      ```
   3. Note the public URL provided by ngrok (e.g., https://abcd1234.ngrok.io). 
   4. Run the Server:
      ```bash
      python manage.py runserver
      ```

## Project Structure
- `api/`: Contains the Django app for the REST API.
- `grocery_room/`: Main project directory with settings and URLs.
- `django-env/`: Virtual environment (local only).
- `requirements.txt`: Dependency list.

## Contributing
Feel free to fork this repository and submit pull requests. Follow Django best practices and ensure tests pass.

## Related Repository
The frontend Grocery Share App will be available at a separate GitHub repository (to be linked later).