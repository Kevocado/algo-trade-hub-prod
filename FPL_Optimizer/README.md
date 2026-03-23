# 🧠 Advanced FPL Optimizer

A comprehensive Fantasy Premier League (FPL) optimization tool with advanced analytics, multiple optimization strategies, and transfer suggestions.
PUBLIC LINK: [https://fploptimizer-76qdwha8usvji3ncz9kvat.streamlit.app/](url)

## 🚀 Features

- **Multiple Optimization Strategies**: Balanced, Form-based, xG/xA focused, Fixture difficulty, Differentials, and Defensive
- **Advanced Analytics**: Expected Goals (xG), Expected Assists (xA), defensive metrics, fixture difficulty analysis
- **Team Analysis**: Analyze your current FPL team and get personalized recommendations
- **Transfer Suggestions**: Get specific transfer recommendations with value calculations
- **Real-time Data**: Fetches live data from the official FPL API
- **Modern Web Interface**: Clean, responsive design with intuitive controls

## 📋 Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Application**:
   ```bash
   python3 app.py
   ```

3. **Open Your Browser**:
   Navigate to `http://localhost:5500`

4. **Use the Tool**:
   - Click "Load Enhanced FPL Data" to initialize
   - Enter your FPL team URL or ID
   - Choose an optimization strategy
   - Get personalized recommendations!

## 🎯 How to Use

### Getting Your FPL Team ID
1. Go to your FPL team page: `https://fantasy.premierleague.com/entry/YOUR_TEAM_ID/`
2. Copy either the full URL or just the team ID number
3. Paste it into the "Your FPL Team Analysis" field

### Optimization Strategies

- **Balanced**: Best overall combination of all metrics
- **Form**: Focus on players in current good form
- **Expected (xG/xA)**: Prioritizes expected goals and assists
- **Fixture**: Optimized for upcoming fixture difficulty
- **Differential**: Lower-owned players for rank climbing
- **Defensive**: High-scoring defenders and clean sheet potential

## 🔧 Technical Details

- **Backend**: Flask (Python)
- **Optimization**: PuLP linear programming
- **Data Source**: Official FPL API
- **Frontend**: HTML5, CSS3, JavaScript
- **Analytics**: Pandas, NumPy for data processing

## 📊 Advanced Metrics

The tool calculates comprehensive player values using:
- Points per million
- Form analysis
- Expected goals and assists (xG/xA)
- Defensive contributions
- Fixture difficulty ratings
- Transfer momentum
- Ownership percentages

## 🛠️ API Endpoints

- `GET /api/initialize` - Load FPL data
- `GET /api/optimize?strategy=X` - Get optimized team
- `GET /api/analyze_team?team_url_or_id=X` - Analyze user team
- `GET /api/players?position=X&sort_by=Y` - Get top players
- `GET /api/compare_strategies` - Compare all strategies

## 📝 Requirements

- Python 3.7+
- Flask 2.3.3
- requests 2.31.0
- pandas 2.1.1
- numpy 1.24.3
- pulp 2.7.0

## 🤝 Contributing

Feel free to submit issues and enhancement requests!

## 📄 License

This project is for educational and personal use. Please respect the FPL API terms of service.
