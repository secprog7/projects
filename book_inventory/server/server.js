const express = require('express');
const mongoose = require('mongoose');
const path = require('path');
const multer = require('multer');
const cors = require('cors');
const axios = require('axios'); // Use axios for HTTP requests
require('dotenv').config({ path: path.resolve(__dirname, '.env') });

const app = express();
const PORT = process.env.PORT || 5000;

// --- Middleware ---
// --- PRODUCTION UPDATE: Configure CORS for production ---
const whitelist = ['http://localhost:3000', 'https://bookkeeper7.netlify.app']; // Replace with your Netlify URL
const corsOptions = {
  origin: function (origin, callback) {
    if (whitelist.indexOf(origin) !== -1 || !origin) {
      callback(null, true)
    } else {
      callback(new Error('Not allowed by CORS'))
    }
  }
}
app.use(cors(corsOptions));
app.use(express.json());
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// --- MongoDB Connection ---
const mongoURI = process.env.MONGO_URI;
if (!mongoURI) {
  console.error("MONGO_URI is not defined. Please check your .env file.");
  process.exit(1);
}

mongoose.connect(mongoURI)
  .then(() => console.log("Successfully connected to MongoDB Atlas!"))
  .catch(err => {
    console.error("Connection error", err);
    process.exit(1);
  });

// --- Multer Setup for Image Uploads ---
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, 'uploads/');
  },
  filename: (req, file, cb) => {
    cb(null, `${Date.now()}-${file.originalname}`);
  }
});
const upload = multer({ storage: storage });

// --- Mongoose Schemas ---
const bookSchema = new mongoose.Schema({
  title: { type: String, required: true },
  author: { type: String, required: true },
  isbn: { type: String, required: true },
  coverImageUrl: { type: String },
  synopsis: { type: String },
  genre: { type: String },
  checkoutDate: { type: Date, default: null },
  checkedOutBy: { type: String, default: null }
});

// Create a text index for advanced search
bookSchema.index({ title: 'text', author: 'text', synopsis: 'text' });

const Book = mongoose.model('Book', bookSchema);

const loanSchema = new mongoose.Schema({
    book: { type: mongoose.Schema.Types.ObjectId, ref: 'Book', required: true },
    borrowerName: { type: String, required: true },
    contactInfo: { type: String },
    loanDate: { type: Date, default: Date.now },
    dueDate: { type: Date, required: true },
    returnDate: { type: Date },
    status: { type: String, enum: ['Loaned', 'Returned', 'Overdue'], default: 'Loaned' },
    notes: { type: String }
});

const Loan = mongoose.model('Loan', loanSchema);

const checkoutSchema = new mongoose.Schema({
    book: { type: mongoose.Schema.Types.ObjectId, ref: 'Book', required: true },
    checkedOutBy: { type: String, required: true },
    checkoutDate: { type: Date, default: Date.now },
    returnDate: { type: Date }
});

const Checkout = mongoose.model('Checkout', checkoutSchema);


// --- API Routes ---

// GET all books with filtering and searching
app.get('/api/books', async (req, res) => {
  try {
    const { genre, q } = req.query;
    let query = {};

    if (genre && genre !== 'All') {
      query.genre = genre;
    }
    if (q) {
      query.$text = { $search: q };
    }

    const books = await Book.find(query).sort({ title: 1 }); // Default sort by title
    res.json(books);
  } catch (error) {
    res.status(500).json({ message: error.message });
  }
});

// POST a new book
app.post('/api/books', upload.single('coverImage'), async (req, res) => {
  const { title, author, isbn, synopsis, genre } = req.body;
  
  // Prevent duplicate ISBNs
  const existingBook = await Book.findOne({ isbn });
  if (existingBook) {
      return res.status(409).json({ message: "A book with this ISBN already exists."});
  }

  const coverImageUrl = req.file ? `/uploads/${req.file.filename}` : req.body.coverImageUrl;

  const newBook = new Book({ title, author, isbn, coverImageUrl, synopsis, genre });
  try {
    const savedBook = await newBook.save();
    res.status(201).json(savedBook);
  } catch (error) {
    res.status(400).json({ message: error.message });
  }
});

// --- NEW FEATURE: PUT route to update a book's details ---
app.put('/api/books/:id/details', upload.single('coverImage'), async (req, res) => {
    try {
        const { id } = req.params;
        const { title, author, isbn, synopsis, genre } = req.body;

        const updateData = { title, author, isbn, synopsis, genre };

        if (req.file) {
            updateData.coverImageUrl = `/uploads/${req.file.filename}`;
            // In a real-world app, you might also delete the old image file from storage here.
        }

        const updatedBook = await Book.findByIdAndUpdate(id, updateData, { new: true });

        if (!updatedBook) {
            return res.status(404).json({ message: "Book not found" });
        }
        res.json(updatedBook);
    } catch (error) {
        // Handle potential duplicate ISBN error on update
        if (error.code === 11000) {
            return res.status(409).json({ message: "Another book with this ISBN already exists."});
        }
        res.status(400).json({ message: error.message });
    }
});


// DELETE a book
app.delete('/api/books/:id', async (req, res) => {
  try {
    const bookId = req.params.id;
    // Also delete associated loans and checkouts
    await Loan.deleteMany({ book: bookId });
    await Checkout.deleteMany({ book: bookId });
    const book = await Book.findByIdAndDelete(bookId);

    if (!book) return res.status(404).json({ message: "Book not found" });
    res.json({ message: "Book and associated records deleted successfully" });
  } catch (error) {
    res.status(500).json({ message: error.message });
  }
});

// GET book info from Google Books API
app.get('/api/lookup', async (req, res) => {
    const { isbn } = req.query;
    if (!isbn) return res.status(400).json({ message: "ISBN is required" });
    try {
        const response = await axios.get(`https://www.googleapis.com/books/v1/volumes?q=isbn:${isbn}`);
        const data = response.data;
        if (data.totalItems === 0) return res.status(404).json({ message: "Book not found" });
        
        const bookInfo = data.items[0].volumeInfo;
        const formattedData = {
            title: bookInfo.title || 'No Title Found',
            author: bookInfo.authors ? bookInfo.authors.join(', ') : 'No Author Found',
            isbn: isbn, // Use the provided ISBN to ensure accuracy
            coverImageUrl: bookInfo.imageLinks?.thumbnail || '',
            synopsis: bookInfo.description || '',
            genre: bookInfo.categories ? bookInfo.categories[0] : ''
        };
        res.json(formattedData);
    } catch (error) {
        console.error("Google Books API Error:", error.message);
        res.status(500).json({ message: "Failed to fetch data from Google Books API" });
    }
});

// UPDATE a book's checkout status
app.put('/api/books/:id/checkout', async (req, res) => {
  try {
    const book = await Book.findById(req.params.id);
    if (!book) return res.status(404).json({ message: 'Book not found' });
    
    const isCheckingOut = req.body.checkoutDate && !book.checkoutDate;
    const isReturning = !req.body.checkoutDate && book.checkoutDate;

    if (isCheckingOut) {
      const existingLoan = await Loan.findOne({ book: book._id, status: 'Loaned' });
      if (existingLoan) {
        return res.status(409).json({ message: "Cannot check out a book that is currently on loan." });
      }

      await Checkout.create({
        book: book._id,
        checkedOutBy: req.body.checkedOutBy,
        checkoutDate: req.body.checkoutDate,
      });
    } else if (isReturning) {
      await Checkout.findOneAndUpdate(
        { book: book._id, returnDate: null },
        { returnDate: new Date() },
        { sort: { checkoutDate: -1 } }
      );
    }
    
    // Update the book document
    book.checkoutDate = req.body.checkoutDate;
    book.checkedOutBy = req.body.checkedOutBy;
    const updatedBook = await book.save();
    
    res.json(updatedBook);
  } catch (error) {
    res.status(500).json({ message: error.message });
  }
});


// --- Loan Routes ---
app.get('/api/loans', async (req, res) => {
    try {
        const loans = await Loan.find({}).populate('book');
        res.json(loans);
    } catch (error) {
        res.status(500).json({ message: error.message });
    }
});

app.post('/api/loans', async (req, res) => {
    const { bookId, borrowerName, contactInfo, dueDate, notes } = req.body;
    try {
        const book = await Book.findById(bookId);
        if (!book) {
            return res.status(404).json({ message: "Book not found." });
        }
        if (book.checkoutDate) {
            return res.status(409).json({ message: `Book is currently checked out by ${book.checkedOutBy}.` });
        }
        const existingLoan = await Loan.findOne({ book: bookId, status: 'Loaned' });
        if (existingLoan) {
            return res.status(409).json({ message: "This book is already on loan." });
        }

        const newLoan = new Loan({ book: bookId, borrowerName, contactInfo, dueDate, notes });
        const savedLoan = await newLoan.save();
        const populatedLoan = await Loan.findById(savedLoan._id).populate('book');
        res.status(201).json(populatedLoan);
    } catch (error) {
        res.status(400).json({ message: error.message });
    }
});

app.put('/api/loans/:id/return', async (req, res) => {
    try {
        const loan = await Loan.findByIdAndUpdate(
            req.params.id,
            { status: 'Returned', returnDate: new Date() },
            { new: true }
        ).populate('book');
        if (!loan) return res.status(404).json({ message: "Loan not found" });
        res.json(loan);
    } catch (error) {
        res.status(500).json({ message: error.message });
    }
});


// --- Analytics Route ---
app.get('/api/analytics/stats', async (req, res) => {
  try {
    // Loan Analytics
    const mostBorrowed = await Loan.aggregate([
      { $group: { _id: '$book', count: { $sum: 1 } } },
      { $sort: { count: -1 } },
      { $limit: 5 },
      { $lookup: { from: 'books', localField: '_id', foreignField: '_id', as: 'bookDetails' } },
      { $unwind: '$bookDetails' },
      { $project: { title: '$bookDetails.title', count: 1, _id: 0 } }
    ]);

    const avgLoanDurationResult = await Loan.aggregate([
      { $match: { status: 'Returned', returnDate: { $ne: null } } },
      { $project: { duration: { $divide: [{ $subtract: ['$returnDate', '$loanDate'] }, 1000 * 60 * 60 * 24] } } },
      { $group: { _id: null, avgDuration: { $avg: '$duration' } } }
    ]);
    const avgLoanDuration = avgLoanDurationResult.length > 0 ? Math.round(avgLoanDurationResult[0].avgDuration) : 0;

    const borrowerHistory = await Loan.aggregate([
      { $group: {
          _id: '$borrowerName',
          totalLoans: { $sum: 1 },
          activeLoans: { $sum: { $cond: [{ $eq: ['$status', 'Loaned'] }, 1, 0] } },
          returnedOnTime: { $sum: { $cond: [{ $and: [ { $eq: ['$status', 'Returned'] }, { $lte: ['$returnDate', '$dueDate'] } ] }, 1, 0] } }
      }},
      { $sort: { totalLoans: -1 } }
    ]);

    // Personal Checkout Analytics
    const mostCheckedOut = await Checkout.aggregate([
        { $group: { _id: '$book', count: { $sum: 1 } } },
        { $sort: { count: -1 } },
        { $limit: 5 },
        { $lookup: { from: 'books', localField: '_id', foreignField: '_id', as: 'bookDetails' } },
        { $unwind: '$bookDetails' },
        { $project: { title: '$bookDetails.title', count: 1, _id: 0 } }
    ]);

    const avgCheckoutDurationResult = await Checkout.aggregate([
        { $match: { returnDate: { $ne: null } } },
        { $project: { duration: { $divide: [{ $subtract: ['$returnDate', '$checkoutDate'] }, 1000 * 60 * 60 * 24] } } },
        { $group: { _id: null, avgDuration: { $avg: '$duration' } } }
    ]);
    const avgCheckoutDuration = avgCheckoutDurationResult.length > 0 ? Math.round(avgCheckoutDurationResult[0].avgDuration) : 0;

    const checkoutHistory = await Checkout.aggregate([
        { $group: { _id: '$checkedOutBy', totalCheckouts: { $sum: 1 }}},
        { $sort: { totalCheckouts: -1 }}
    ]);

    res.json({
      mostBorrowed,
      avgLoanDuration,
      borrowerHistory,
      mostCheckedOut,
      avgCheckoutDuration,
      checkoutHistory
    });

  } catch (error) {
    res.status(500).json({ message: error.message });
  }
});

// --- Server Production Static Build ---
if (process.env.NODE_ENV === 'production') {
    app.use(express.static(path.join(__dirname, '../client/build')));

    app.get('*', (req, res) => {
        res.sendFile(path.resolve(__dirname, '../client/build', 'index.html'));
    });
}


// --- Server Start ---
app.listen(PORT, () => {
  console.log(`Server is running on http://localhost:${PORT}`);
});

