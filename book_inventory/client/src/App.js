import React, { useState, useEffect, useCallback } from 'react';
import { Scanner } from '@yudiel/react-qr-scanner';
import './App.css';

// --- Production-Ready API URL ---
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';


// --- Helper function to format image URLs ---
const getImageUrl = (url) => {
  if (!url) return null;
  // If the URL is already absolute, return it as is. Otherwise, prefix it.
  if (url.startsWith('http')) {
    return url;
  }
  // Use the API_URL for constructing local paths in production
  return `${API_URL}${url}`;
};

function App() {
  // --- STATE for page navigation ---
  const [page, setPage] = useState('library');

  // --- NEW FEATURE (EDIT): State to track which book is being edited ---
  const [editingBook, setEditingBook] = useState(null);

  // --- NEW FEATURE (SCANNER): State for scanner visibility ---
  const [isScannerOpen, setIsScannerOpen] = useState(false);
  // --- FIX: Added missing state for handling the scanned ISBN result ---
  const [scannedIsbn, setScannedIsbn] = useState(null);

  // Existing States
  const [books, setBooks] = useState([]);
  const [form, setForm] = useState({ title: '', author: '', isbn: '', coverImageUrl: '', synopsis: '', genre: '' });
  const [coverImage, setCoverImage] = useState(null);
  const [selectedBook, setSelectedBook] = useState(null);
  const [filterGenre, setFilterGenre] = useState('All');
  const [genres, setGenres] = useState(['All']);
  const [searchTerm, setSearchTerm] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isbnToLookUp, setIsbnToLookUp] = useState('');

  // Loan States
  const [loans, setLoans] = useState([]);
  const [isLoanModalOpen, setIsLoanModalOpen] = useState(false);
  const [loanForm, setLoanForm] = useState({ borrowerName: '', contactInfo: '', dueDate: '', notes: '' });
  const [currentBookToLoan, setCurrentBookToLoan] = useState(null);
  
  // States for editing checkout
  const [editingCheckout, setEditingCheckout] = useState(false);
  const [checkoutForm, setCheckoutForm] = useState({ date: '', name: '' });


  // Analytics State
  const [stats, setStats] = useState(null);


  // --- Data Fetching ---
  const fetchBooks = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterGenre !== 'All') params.append('genre', filterGenre);
      if (searchTerm) params.append('q', searchTerm);
      
      const response = await fetch(`${API_URL}/api/books?${params.toString()}`);
      if (!response.ok) throw new Error('Network response was not ok');
      const data = await response.json();
      setBooks(data);
    } catch (error) {
      console.error("Failed to fetch books:", error);
    }
  }, [filterGenre, searchTerm]);
  
  const fetchLoans = useCallback(async () => {
      try {
          const response = await fetch(`${API_URL}/api/loans`);
          if (!response.ok) throw new Error('Failed to fetch loans');
          const data = await response.json();
          setLoans(data);
      } catch (error) {
          console.error("Failed to fetch loans:", error);
      }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
        const response = await fetch(`${API_URL}/api/analytics/stats`);
        if (!response.ok) throw new Error('Failed to fetch stats');
        const data = await response.json();
        setStats(data);
    } catch (error) {
        console.error("Failed to fetch stats:", error);
    }
  }, []);

  const handleLookup = useCallback(async (isbn) => {
    if (!isbn) return;
    try {
      const response = await fetch(`${API_URL}/api/lookup?isbn=${isbn}`);
      if (!response.ok) throw new Error('Book not found');
      const data = await response.json();
      setForm(data);
      setIsAddModalOpen(true);
      setIsbnToLookUp('');
    } catch (error) {
      alert('Could not find a book with that ISBN.');
    }
  }, []);

  // --- FIX: Added useEffect to process the scanned ISBN after the scanner modal closes ---
  useEffect(() => {
    if (scannedIsbn) {
      // Use a small timeout to ensure the scanner modal has fully transitioned out
      setTimeout(() => {
        handleLookup(scannedIsbn);
        setScannedIsbn(null); // Reset after processing
      }, 100);
    }
  }, [scannedIsbn, handleLookup]);


  useEffect(() => {
    fetchBooks();
    fetchLoans();
    fetchStats();
  }, [fetchBooks, fetchLoans, fetchStats]);

  useEffect(() => {
    const timerId = setTimeout(() => { if (page === 'library') fetchBooks(); }, 300);
    return () => clearTimeout(timerId);
  }, [filterGenre, searchTerm, page, fetchBooks]);

  useEffect(() => {
    const fetchAllBooksForGenres = async () => {
      try {
        const response = await fetch(`${API_URL}/api/books`);
        if (!response.ok) throw new Error('Failed to fetch all books for genres');
        const allBooks = await response.json();
        const allGenres = new Set(allBooks.map(book => book.genre).filter(Boolean));
        setGenres(['All', ...Array.from(allGenres)]);
      } catch (error) { console.error(error); }
    };
    fetchAllBooksForGenres();
  }, [books]);


  // --- Form Handlers ---
  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setForm({ ...form, [name]: value });
  };

  const handleFileChange = (e) => {
    setCoverImage(e.target.files[0]);
  };
  
  const handleLoanInputChange = (e) => {
      const { name, value } = e.target;
      setLoanForm({...loanForm, [name]: value });
  }

  // --- Submission Handlers ---
  const handleAddSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    Object.keys(form).forEach(key => formData.append(key, form[key]));
    if (coverImage) {
      formData.append('coverImage', coverImage);
    }

    try {
      const response = await fetch(`${API_URL}/api/books`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || 'Failed to add book');
      }
      
      setForm({ title: '', author: '', isbn: '', coverImageUrl: '', synopsis: '', genre: '' });
      setCoverImage(null);
      setIsAddModalOpen(false);
      fetchBooks();
    } catch (error) {
      console.error("Error adding book:", error);
      alert(`Error: ${error.message}`);
    }
  };

  const handleUpdateSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    Object.keys(form).forEach(key => {
        if (['_id', 'checkoutDate', 'checkedOutBy'].indexOf(key) === -1) {
            formData.append(key, form[key]);
        }
    });

    if (coverImage) {
        formData.append('coverImage', coverImage);
    }

    try {
        const response = await fetch(`${API_URL}/api/books/${editingBook._id}/details`, {
            method: 'PUT',
            body: formData,
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.message || 'Failed to update book');
        }
        
        closeAddEditModal();
        fetchBooks();
    } catch (error) {
        console.error("Error updating book:", error);
        alert(`Error: ${error.message}`);
    }
  };

  const handleLoanSubmit = async (e) => {
      e.preventDefault();
      try {
          const response = await fetch(`${API_URL}/api/loans`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                  bookId: currentBookToLoan._id,
                  ...loanForm
              })
          });
          if (!response.ok) {
            const err = await response.json();
            throw new Error(err.message || 'Failed to create loan');
          }
          
          setIsLoanModalOpen(false);
          setLoanForm({ borrowerName: '', contactInfo: '', dueDate: '', notes: '' });
          fetchLoans();
          fetchBooks();
          fetchStats();
          setSelectedBook(null);
      } catch (error) {
          console.error("Error creating loan:", error);
          alert(`Error: ${error.message}`);
      }
  }

  const handleDelete = async (bookId) => {
    if (window.confirm('Are you sure you want to delete this book? This will also remove all associated loan and checkout records.')) {
      try {
        const response = await fetch(`${API_URL}/api/books/${bookId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete book');
        fetchBooks();
        fetchLoans();
        fetchStats();
        setSelectedBook(null);
      } catch (error) { console.error("Error deleting book:", error); }
    }
  };
  
  const handleReturn = async (loanId) => {
      try {
          const response = await fetch(`${API_URL}/api/loans/${loanId}/return`, {
              method: 'PUT',
          });
          if (!response.ok) throw new Error('Failed to return book');
          fetchLoans();
          fetchStats();
      } catch (error) {
          console.error("Error returning book:", error);
      }
  };

  const handleCheckoutUpdate = async (bookId, updateData) => {
    try {
      const response = await fetch(`${API_URL}/api/books/${bookId}/checkout`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateData)
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || 'Failed to update book');
      }
      const updatedBook = await response.json();
      
      setBooks(books.map(b => b._id === bookId ? updatedBook : b));
      setSelectedBook(updatedBook); 
      setEditingCheckout(false);
      fetchStats();
    } catch (error) {
      console.error("Error updating book:", error);
      alert(`Error: ${error.message}`);
    }
  };
  
  // --- Modal Openers ---
  const openLoanModal = (book) => {
      setCurrentBookToLoan(book);
      const twoWeeksFromNow = new Date();
      twoWeeksFromNow.setDate(twoWeeksFromNow.getDate() + 14);
      setLoanForm({ borrowerName: '', contactInfo: '', dueDate: twoWeeksFromNow.toISOString().split('T')[0], notes: '' });
      setIsLoanModalOpen(true);
  }

  const openEditModal = (book) => {
      setSelectedBook(null);
      setEditingBook(book);
      setForm(book);
      setIsAddModalOpen(true);
  };

  const closeAddEditModal = () => {
    setIsAddModalOpen(false);
    setEditingBook(null);
    setForm({ title: '', author: '', isbn: '', coverImageUrl: '', synopsis: '', genre: '' });
    setCoverImage(null);
  };

  // --- Helper variables for rendering ---
  const activeLoans = loans.filter(loan => loan.status === 'Loaned' || loan.status === 'Overdue');
  const personallyCheckedOutBooks = books.filter(book => book.checkoutDate);
  const isSelectedBookOnLoan = selectedBook && activeLoans.some(loan => loan.book?._id === selectedBook._id);
  const isBookUnavailable = isSelectedBookOnLoan || (selectedBook && selectedBook.checkoutDate);


  return (
    <div className="App">
      <header className="App-header">
        <h1>Book Keeper</h1>
        <nav className="app-nav">
          <button className={`nav-btn ${page === 'library' ? 'active' : ''}`} onClick={() => setPage('library')}>
            My Library
          </button>
          <button className={`nav-btn ${page === 'analytics' ? 'active' : ''}`} onClick={() => setPage('analytics')}>
            Analytics
          </button>
        </nav>
      </header>

      <main>
        {page === 'library' && (
          <>
            <div className="library-header">
                <div className="top-actions">
                    <div className="search-container">
                        <input type="text" placeholder="Search by title, author, etc..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="search-input" />
                    </div>
                    <div className="isbn-lookup-container">
                        <input 
                            type="text" 
                            placeholder="Find by ISBN..." 
                            value={isbnToLookUp} 
                            onChange={(e) => setIsbnToLookUp(e.target.value)} 
                            className="search-input"
                        />
                        <button className="lookup-btn" onClick={() => handleLookup(isbnToLookUp)}>Find</button>
                        <button className="scan-btn" onClick={() => setIsScannerOpen(true)}>
                            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><line x1="7" x2="17" y1="12" y2="12"/></svg>
                        </button>
                    </div>
                    <div className="main-actions">
                        <button className="add-book-btn" onClick={() => setIsAddModalOpen(true)}>+ Add Manually</button>
                    </div>
                </div>
                <div className="filter-pills">
                    <span className="filter-label">Filter by:</span>
                    <select value={filterGenre} onChange={(e) => setFilterGenre(e.target.value)}>
                        {genres.map(genre => <option key={genre} value={genre}>{genre}</option>)}
                    </select>
                </div>
            </div>

            {activeLoans.length > 0 && 
              <section>
                  <h2>On Loan</h2>
                  <ul className="loan-list">
                      {activeLoans.map(loan => loan.book && (
                          <li key={loan._id} className="loan-card">
                              <img src={getImageUrl(loan.book.coverImageUrl)} alt={loan.book.title} />
                              <div className="loan-info">
                                  <strong>{loan.book.title}</strong>
                                  <span>To: {loan.borrowerName}</span>
                                  <span>Due: {new Date(loan.dueDate).toLocaleDateString()}</span>
                              </div>
                              <button onClick={() => handleReturn(loan._id)} className="return-btn">Return</button>
                          </li>
                      ))}
                  </ul>
              </section>
            }
            
            {personallyCheckedOutBooks.length > 0 &&
              <section>
                  <h2>Personally Checked Out</h2>
                  <ul className="checkout-list">
                      {personallyCheckedOutBooks.map(book => (
                          <li key={book._id} className="checkout-card">
                              <img src={getImageUrl(book.coverImageUrl)} alt={book.title} />
                              <div className="checkout-info">
                                  <strong>{book.title}</strong>
                                  <span>To: {book.checkedOutBy}</span>
                                  <span>Since: {new Date(book.checkoutDate).toLocaleDateString()}</span>
                              </div>
                              <button 
                                  onClick={() => handleCheckoutUpdate(book._id, { checkoutDate: null, checkedOutBy: null })} 
                                  className="checkout-return-btn"
                              >
                                  Return
                              </button>
                          </li>
                      ))}
                  </ul>
              </section>
            }

            <section>
              <h2>My Collection ({books.length} books)</h2>
              <ul className="book-grid">
                {books.map(book => (
                  <li 
                    key={book._id} 
                    className="book-card"
                    onClick={() => setSelectedBook(book)}
                  >
                    <div className="cover-wrapper">
                        {getImageUrl(book.coverImageUrl) ? <img src={getImageUrl(book.coverImageUrl)} alt={`Cover of ${book.title}`} className="book-cover-image" /> : <div className="book-cover-placeholder"><span>No Cover</span></div>}
                        {(activeLoans.some(l => l.book?._id === book._id) || book.checkoutDate) && (
                          <div className="checked-out-overlay">
                            <span>{book.checkoutDate ? 'Checked Out' : 'On Loan'}</span>
                          </div>
                        )}
                    </div>
                    <div className="book-info">
                      <h3>{book.title}</h3>
                      <p>{book.author}</p>
                    </div>
                  </li>
                ))}
              </ul>
              {books.length === 0 && <p>Your library is empty or no books match the current filter.</p>}
            </section>
          </>
        )}

        {page === 'analytics' && (
          <section>
            <h2>Analytics Dashboard</h2>
            {stats ? (
              <div className="analytics-grid">
                <div className="stat-card">
                  <h3>Most Borrowed Books (Loans)</h3>
                  {stats.mostBorrowed.length > 0 ? (
                    <ol>
                      {stats.mostBorrowed.map(book => (
                        <li key={book.title}>
                          {book.title} <span>({book.count} loans)</span>
                        </li>
                      ))}
                    </ol>
                  ) : <p>No loan data yet.</p>}
                </div>

                <div className="stat-card">
                  <h3>Avg. Loan Duration</h3>
                  <p className="stat-big-number">{stats.avgLoanDuration}<span> days</span></p>
                </div>

                <div className="stat-card">
                  <h3>Most Checked Out (Personal)</h3>
                  {stats.mostCheckedOut.length > 0 ? (
                    <ol>
                      {stats.mostCheckedOut.map(book => (
                        <li key={book.title}>
                          {book.title} <span>({book.count} checkouts)</span>
                        </li>
                      ))}
                    </ol>
                  ) : <p>No checkout data yet.</p>}
                </div>

                <div className="stat-card">
                  <h3>Avg. Checkout Duration</h3>
                  <p className="stat-big-number">{stats.avgCheckoutDuration}<span> days</span></p>
                </div>

                <div className="stat-card full-width">
                  <h3>Loan Borrower History</h3>
                  {stats.borrowerHistory.length > 0 ? (
                    <table className="borrower-table">
                      <thead>
                        <tr>
                          <th>Borrower</th>
                          <th>Total Loans</th>
                          <th>Returned On Time</th>
                          <th>Active Loans</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.borrowerHistory.map(borrower => (
                          <tr key={borrower._id}>
                            <td>{borrower._id}</td>
                            <td>{borrower.totalLoans}</td>
                            <td>{borrower.returnedOnTime}</td>
                            <td>{borrower.activeLoans}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <p>No borrower data yet.</p>}
                </div>

                <div className="stat-card full-width">
                  <h3>Personal Checkout History</h3>
                  {stats.checkoutHistory.length > 0 ? (
                    <table className="borrower-table">
                      <thead>
                        <tr>
                          <th>Checked Out By</th>
                          <th>Total Checkouts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.checkoutHistory.map(person => (
                          <tr key={person._id}>
                            <td>{person._id}</td>
                            <td>{person.totalCheckouts}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <p>No personal checkout data yet.</p>}
                </div>
              </div>
            ) : <p>Loading stats...</p>}
          </section>
        )}
      </main>


      {/* --- MODALS --- */}
      {selectedBook && (
        <div className="modal-overlay" onClick={() => setSelectedBook(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="close-btn" onClick={() => setSelectedBook(null)}>×</button>
            <img src={getImageUrl(selectedBook.coverImageUrl)} alt={`Cover of ${selectedBook.title}`} className="modal-cover-image" />
            <div className="modal-info">
              <h2>{selectedBook.title}</h2>
              <h3>by {selectedBook.author}</h3>
              <p><strong>ISBN:</strong> {selectedBook.isbn}</p>
              <p><strong>Genre:</strong> {selectedBook.genre}</p>
              
              <div className="checkout-section">
                <strong>Personal Checkout:</strong>
                {selectedBook.checkoutDate ? (
                  <div>
                    <span>{`Checked out by ${selectedBook.checkedOutBy} on ${new Date(selectedBook.checkoutDate).toLocaleDateString()}`}</span>
                    <button onClick={() => handleCheckoutUpdate(selectedBook._id, { checkoutDate: null, checkedOutBy: null })}>Return</button>
                  </div>
                ) : isSelectedBookOnLoan ? (
                  <div>
                    <span>Unavailable (Currently on loan)</span>
                  </div>
                ) : editingCheckout ? (
                  <div className="checkout-form">
                    <input 
                        type="date" 
                        value={checkoutForm.date} 
                        onChange={(e) => setCheckoutForm({...checkoutForm, date: e.target.value})}
                    />
                     <input 
                        type="text" 
                        placeholder="Your Name"
                        value={checkoutForm.name} 
                        onChange={(e) => setCheckoutForm({...checkoutForm, name: e.target.value})}
                    />
                    <button onClick={() => handleCheckoutUpdate(selectedBook._id, { checkoutDate: checkoutForm.date, checkedOutBy: checkoutForm.name })}>Save</button>
                    <button onClick={() => setEditingCheckout(false)}>Cancel</button>
                  </div>
                ) : (
                  <div>
                    <span>Available</span>
                    <button onClick={() => { setEditingCheckout(true); setCheckoutForm({date: new Date().toISOString().split('T')[0], name: '' }) }}>Set Checkout</button>
                  </div>
                )}
              </div>

              <p>{selectedBook.synopsis}</p>
              <div className="modal-actions">
                {isBookUnavailable ? (
                    <p className="on-loan-status">
                        {isSelectedBookOnLoan ? `On loan to ${loans.find(l=>l.book?._id === selectedBook._id)?.borrowerName}` : `Checked out by ${selectedBook.checkedOutBy}`}
                    </p>
                ) : (
                  <button onClick={() => openLoanModal(selectedBook)} className="loan-book-btn">Loan This Book</button>
                )}
                <button onClick={() => openEditModal(selectedBook)} className="edit-btn">Edit</button>
                <button onClick={() => handleDelete(selectedBook._id)} className="delete-btn">Delete Book</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isAddModalOpen && (
        <div className="modal-overlay" onClick={closeAddEditModal}>
          <div className="modal-content add-book-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="close-btn" onClick={closeAddEditModal}>×</button>
            <h2>{editingBook ? 'Edit Book Details' : 'Add a New Book'}</h2>
            <form onSubmit={editingBook ? handleUpdateSubmit : handleAddSubmit} className="add-book-form">
              <div className="form-row">
                <input type="text" name="title" placeholder="Title" value={form.title} onChange={handleInputChange} required />
                <input type="text" name="author" placeholder="Author" value={form.author} onChange={handleInputChange} required />
              </div>
              <div className="form-row">
                <input type="text" name="isbn" placeholder="ISBN" value={form.isbn} onChange={handleInputChange} required />
                <input type="text" name="genre" placeholder="Genre" value={form.genre} onChange={handleInputChange} />
              </div>
              <div className="form-row">
                <textarea name="synopsis" placeholder="Synopsis" value={form.synopsis} onChange={handleInputChange} />
              </div>
              <div className="form-row">
                <label htmlFor="coverImageInput">Cover Image (optional):</label>
                <input id="coverImageInput" type="file" name="coverImage" onChange={handleFileChange} />
              </div>
              <button type="submit" className="cta-btn">{editingBook ? 'Save Changes' : 'Add Book to Inventory'}</button>
            </form>
          </div>
        </div>
      )}
      
      {isLoanModalOpen && currentBookToLoan && (
        <div className="modal-overlay" onClick={() => setIsLoanModalOpen(false)}>
            <div className="modal-content add-book-modal-content" onClick={(e) => e.stopPropagation()}>
                <button className="close-btn" onClick={() => setIsLoanModalOpen(false)}>×</button>
                <h2>Loan "{currentBookToLoan.title}"</h2>
                <form onSubmit={handleLoanSubmit} className="add-book-form">
                    <div className="form-row">
                        <label htmlFor="borrowerName">Borrower's Name:</label>
                        <input id="borrowerName" type="text" name="borrowerName" placeholder="Borrower's Name" value={loanForm.borrowerName} onChange={handleLoanInputChange} required />
                    </div>
                    <div className="form-row">
                        <label htmlFor="contactInfo">Contact Info:</label>
                        <input id="contactInfo" type="text" name="contactInfo" placeholder="Contact Info (Email/Phone)" value={loanForm.contactInfo} onChange={handleLoanInputChange} />
                    </div>
                     <div className="form-row">
                        <label htmlFor="dueDate">Due Date:</label>
                        <input id="dueDate" type="date" name="dueDate" value={loanForm.dueDate} onChange={handleLoanInputChange} required />
                    </div>
                    <div className="form-row">
                         <label htmlFor="notes">Notes:</label>
                        <textarea id="notes" name="notes" placeholder="Notes (e.g., condition)" value={loanForm.notes} onChange={handleLoanInputChange}></textarea>
                    </div>
                    <button type="submit" className="cta-btn">Confirm Loan</button>
                </form>
            </div>
        </div>
      )}

      {isScannerOpen && (
          <div className="scanner-modal">
               <Scanner
                  onResult={(result) => {
                      // --- FIX: Store the result in state and close the modal ---
                      setScannedIsbn(result.getText());
                      setIsScannerOpen(false);
                  }}
                  onError={(error) => {
                      console.error(error?.message);
                  }}
                  videoStyle={{ 
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%', 
                    height: '100%', 
                    objectFit: 'cover',
                    zIndex: 1999
                  }}
                  formats={["ean_13"]}
              />
              <div className="scanner-content">
                  <div className="viewfinder">
                      <div className="scanning-line"></div>
                  </div>
                  <p className="scanner-prompt">Align the book's barcode within the frame</p>
              </div>
              <button className="close-scanner-btn" onClick={() => setIsScannerOpen(false)}>×</button>
          </div>
      )}
    </div>
  );
}

export default App;

