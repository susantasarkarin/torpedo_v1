const express = require('express');
const mongoose = require('mongoose');
const bodyParser = require('body-parser');
const session = require('express-session');
const User = require('./models/User');

const app = express();
const PORT = process.env.PORT || 3000;

// Connect to MongoDB
mongoose.connect('mongodb://localhost:27017/live-dinner', {
  useNewUrlParser: true,
  useUnifiedTopology: true
}).then(() => console.log('MongoDB connected'))
  .catch(err => console.log(err));

// Middleware
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(session({
  secret: 'your-secret-key',
  resave: false,
  saveUninitialized: true
}));

// Serve static files
app.use(express.static('.'));

// Routes
app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

app.get('/dashboard', (req, res) => {
  if (req.session.user) {
    res.sendFile(__dirname + '/dashboard.html');
  } else {
    res.redirect('/');
  }
});

app.post('/login', async (req, res) => {
  const { userid, password } = req.body;
  try {
    const user = await User.findOne({ userid });
    if (user && await user.comparePassword(password)) {
      req.session.user = user;
      res.redirect('/dashboard');
    } else {
      res.redirect('/?error=invalid');
    }
  } catch (err) {
    res.status(500).send('Server error');
  }
});

// Route to add sample user
app.post('/register', async (req, res) => {
  const { userid, password } = req.body;
  try {
    const user = new User({ userid, password });
    await user.save();
    res.send('User registered');
  } catch (err) {
    res.status(500).send('Error registering user');
  }
});

app.get('/logout', (req, res) => {
  req.session.destroy(err => {
    if (err) {
      return res.status(500).send('Could not log out');
    }
    res.redirect('/');
  });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
