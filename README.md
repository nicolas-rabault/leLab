# LeLab - Web Interface for LeRobot

A modern web-based interface for controlling and monitoring robots using the [LeRobot](https://github.com/huggingface/lerobot) framework. This application provides an intuitive dashboard for robot teleoperation, data recording, and calibration management.

## 🤖 About

LeLab bridges the gap between LeRobot's powerful robotics capabilities and user-friendly web interfaces. It offers:

- **Real-time robot control** through an intuitive web dashboard
- **Dataset recording** for training machine learning models
- **Live teleoperation** with WebSocket-based real-time feedback
- **Configuration management** for leader/follower robot setups
- **Joint position monitoring** and visualization

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Frontend      │    │   FastAPI        │    │   LeRobot       │
│   (React/TS)    │◄──►│   Backend        │◄──►│   Framework     │
│                 │    │                  │    │                 │
│   • Dashboard   │    │   • REST APIs    │    │   • Robot       │
│   • Controls    │    │   • WebSockets   │    │     Control     │
│   • Monitoring  │    │   • Recording    │    │   • Sensors     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## ✨ Features

### 🎮 Robot Control

- **Teleoperation**: Direct robot arm control through web interface
- **Joint monitoring**: Real-time joint position feedback via WebSocket
- **Safety controls**: Start/stop teleoperation with status monitoring

### 📹 Data Recording

- **Dataset creation**: Record episodes for training ML models
- **Session management**: Start, stop, and manage recording sessions
- **Episode controls**: Skip to next episode or re-record current one
- **Real-time status**: Monitor recording progress and status

### ⚙️ Configuration

- **Config management**: Handle leader and follower robot configurations
- **Calibration support**: Load and manage calibration settings
- **Health monitoring**: System health checks and diagnostics

### 🌐 Web Interface

- **Modern UI**: Built with React, TypeScript, and Tailwind CSS
- **Real-time updates**: WebSocket integration for live data
- **Responsive design**: Works on desktop and mobile devices

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Node.js 16+ (for frontend development)
- LeRobot framework installed and configured
- Compatible robot hardware

### Installation

1. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd leLab
   ```

2. **Install the Python backend**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. **Install frontend dependencies** (for development)
   ```bash
   cd frontend
   npm install
   ```

### Running the Application

After installation, you can use the `lelab` command-line tool:

```bash
# Start both backend and frontend (default)
lelab

# Or explicitly start both servers
lelab both
# or
lelab dev

# Start only the backend server
lelab backend

# Start only the frontend development server
lelab frontend
```

**Command Options:**

- `lelab` or `lelab both` or `lelab dev` - Starts both FastAPI backend (port 8000) and Vite frontend (port 5173)
- `lelab backend` - Starts only the FastAPI backend server on `http://localhost:8000`
- `lelab frontend` - Starts only the Vite frontend development server on `http://localhost:5173`

**Access the application:**

- **Full-stack mode**: Visit `http://localhost:5173` (frontend) - it will proxy API calls to the backend
- **Backend only**: Visit `http://localhost:8000` (serves both API and static frontend files)
- **API documentation**: `http://localhost:8000/docs`

## 📖 API Documentation

Once the server is running, visit:

- **Interactive API docs**: `http://localhost:8000/docs`
- **OpenAPI spec**: `http://localhost:8000/openapi.json`

### Key Endpoints

- `POST /move-arm` - Start robot teleoperation
- `POST /stop-teleoperation` - Stop current teleoperation
- `GET /joint-positions` - Get current joint positions
- `POST /start-recording` - Begin dataset recording
- `POST /stop-recording` - End recording session
- `GET /get-configs` - Retrieve available configurations
- `WS /ws/joint-data` - WebSocket for real-time joint data

## 🏗️ Project Structure

```
leLab/
├── app/                    # FastAPI backend
│   ├── main.py            # Main FastAPI application
│   ├── recording.py       # Dataset recording logic
│   ├── calibrating.py     # Robot calibration
│   ├── config.py          # Configuration management
│   └── static/            # Static web files
├── frontend/              # React frontend
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   ├── hooks/         # Custom React hooks
│   │   └── contexts/      # React contexts
│   ├── public/            # Static assets
│   └── package.json       # Frontend dependencies
├── pyproject.toml         # Python project configuration
└── README.md             # This file
```

## 🔧 Development

### Backend Development

```bash
# Install in editable mode
pip install -e .

# Run with auto-reload
python -m app.main
```

### Frontend Development

```bash
cd frontend
npm run dev          # Development server
npm run build        # Production build
npm run preview      # Preview production build
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [LeRobot](https://github.com/huggingface/lerobot) - The underlying robotics framework
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework for building APIs
- [React](https://reactjs.org/) - Frontend user interface library

---

**Note**: Make sure your LeRobot environment is properly configured and your robot hardware is connected before running the application.
