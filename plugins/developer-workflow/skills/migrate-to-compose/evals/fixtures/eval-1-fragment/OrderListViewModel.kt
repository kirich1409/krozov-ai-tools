package com.example.app.orders

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class OrderListState(
    val orders: List<Order> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null
)

data class Order(
    val id: String,
    val title: String,
    val status: OrderStatus,
    val amount: String,
    val date: String
)

enum class OrderStatus { PENDING, IN_PROGRESS, COMPLETED, CANCELLED }

@HiltViewModel
class OrderListViewModel @Inject constructor(
    private val orderRepository: OrderRepository
) : ViewModel() {

    private val _state = MutableStateFlow(OrderListState(isLoading = true))
    val state: StateFlow<OrderListState> = _state.asStateFlow()

    init { loadOrders() }

    fun refresh() { loadOrders() }

    fun onOrderClick(order: Order) {
        // navigate to detail — handled via navigation event (not shown for brevity)
    }

    fun onCancelOrder(order: Order) {
        viewModelScope.launch {
            orderRepository.cancelOrder(order.id)
            loadOrders()
        }
    }

    private fun loadOrders() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, error = null)
            try {
                val orders = orderRepository.getOrders()
                _state.value = OrderListState(orders = orders, isLoading = false)
            } catch (e: Exception) {
                _state.value = OrderListState(error = e.message ?: "Unknown error", isLoading = false)
            }
        }
    }
}
