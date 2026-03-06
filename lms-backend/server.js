// lms-backend/server.js
const express = require('express');
const mongoose = require('mongoose');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const { Configuration, OpenAIApi } = require('openai');
const cors = require('cors');
const app = express();
app.use(cors());
app.use(express.json());

mongoose.connect(process.env.MONGO_URI, { useNewUrlParser: true, useUnifiedTopology: true });

const UserSchema = new mongoose.Schema({
    email: String,
    language: String,
    institution: String,
    subscriptionId: String,
    paymentHistory: [{ date: Date, amount: Number, status: String }],
    messages: [{ topic: String, score: Number, message: String, date: Date }]
});
const User = mongoose.model('User', UserSchema);

const openai = new OpenAIApi(new Configuration({ apiKey: process.env.OPENAI_API_KEY }));

app.post('/api/register', async (req, res) => {
    const { email, institution, language, plan } = req.body;
    const customer = await stripe.customers.create({ email, metadata: { institution } });
    const priceId = process.env[plan.toUpperCase() + '_PRICE_ID'] || process.env.INDIVIDUAL_PRICE_ID;
    const subscription = await stripe.subscriptions.create({
        customer: customer.id,
        items: [{ price: priceId }],
        payment_behavior: 'default_incomplete'
    });
    const user = new User({ email, language, institution, subscriptionId: subscription.id });
    await user.save();
    res.json({ success: true, subId: subscription.id, language });
});

app.get('/api/dashboard/:userId', async (req, res) => {
    const user = await User.findOne({ subscriptionId: req.params.userId });
    const payments = await stripe.charges.list({ customer: user.subscriptionId });
    user.paymentHistory = payments.data.map(p => ({ date: new Date(p.created * 1000), amount: p.amount, status: p.status }));
    await user.save();
    res.json(user);
});

app.post('/api/quiz/submit', async (req, res) => {
    const { userId, score, topic } = req.body;
    const user = await User.findOne({ subscriptionId: userId });
    if (score < 80) {
        const response = await openai.createCompletion({
            model: 'gpt-4',
            prompt: `Student scored ${score}% on ${topic}. Suggest improvement with VR sim or video in a friendly tone.`,
            max_tokens: 100
        });
        user.messages.push({ topic, score, message: response.data.choices[0].text, date: new Date() });
        await user.save();
    }
    res.json({ success: true });
});

app.get('/api/recommendations/:userId', async (req, res) => {
    const user = await User.findOne({ subscriptionId: req.params.userId });
    const viewed = user.messages.map(m => m.topic);
    const response = await openai.createCompletion({
        model: 'gpt-4',
        prompt: `Given viewed: ${viewed.join(', ')}, recommend 3 medical topics.`,
        max_tokens: 100
    });
    res.json({ recommendations: response.data.choices[0].text.split('\n').filter(t => t) });
});

app.post('/api/auth0/callback', async (req, res) => {
    const { token } = req.body;
    const decoded = jwt.verify(token, process.env.AUTH0_PUBLIC_KEY);
    const user = await User.findOne({ auth0Id: decoded.sub });
    if (!user) return res.status(401).json({ error: 'User not found' });
    res.json({ userId: user.subscriptionId, language: user.language });
});

app.listen(process.env.PORT || 3000, () => console.log('LMS Backend on port 3000'));
