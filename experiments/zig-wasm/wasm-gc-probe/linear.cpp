struct Cell { int value; Cell *next; };
extern "C" int read_cell(Cell *cell) { return cell->value; }
