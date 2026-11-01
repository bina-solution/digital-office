

// company required error object
class UnableToGuessCompany extends Error {
  constructor(message) {
    super(message);
    this.name = "UnableToGuessCompany";
  }
}



module.exports = { UnableToGuessCompany };