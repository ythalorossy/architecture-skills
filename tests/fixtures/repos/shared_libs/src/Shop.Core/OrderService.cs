using Shop.Contracts;

namespace Shop.Core;

public class OrderService
{
    public Order Place(string id) => new Order(id, 0m);
}
